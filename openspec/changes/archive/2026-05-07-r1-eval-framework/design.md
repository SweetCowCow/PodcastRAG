## Context

R1 評測框架第二塊。R1.1 已上線收 thumbs / citation_click 真實使用者訊號（屬 R1.3 才會餵回 golden set sentinel）。本 change 的目標是讓 R3 / R2 / R4 改動有客觀 baseline 與回歸測試。

當前狀態：
- 後端有 `/shows/{id}/query` POST endpoint 可拿 RAG 答案 + sources（ChatResponse 含 query_id / answer / citations）
- 沒有任何自動跑指標的機制
- 沒有 golden set
- LLM 都走 Zeabur AI Hub（answer=gpt-4o，rewrite=gpt-4o-mini）；本次 judge 評選後再決定 production judge 是否同走 hub

Stakeholders：
- 主要使用者：開發者（跑 eval 看新改動有沒有破壞 baseline）
- 次要使用者：admin（每月看是否要補 golden set）
- 不是給終端使用者用的（前台無感）

## Goals / Non-Goals

**Goals**
- 自動跑全套指標（Recall@5 / MRR / Faithfulness / AnswerRelevancy）+ 輸出可比對 JSON
- 至少一個節目（這又沒有很屌）有 50 題 golden set
- judge model 選擇是「資料驅動」而非拍腦袋
- skill 化讓未來新節目產 golden set 落地時間 < 1 小時

**Non-Goals**
- 不在 PR CI 跑 judge metric（每跑一次成本 ~$0.5；nightly 跑 main 即可）
- 不做 Dashboard 視覺化（屬 R1.3）
- 不接 Langfuse（屬 R1.3）

## Decisions

### Judge model 用 Spearman 相關係數選

跟人工 mini-set 標分（20 題 × 1-5 scale）算 Spearman；> 0.7 才晉級。Spearman 比 Pearson 適合此情境因為人工標分是序位 score。為何不用 Kendall tau：實作上等價，Spearman 較直觀。

替代方案 — RMSE 對人工分數絕對誤差。Reject：人工分絕對值不重要（人對 3 vs 4 vs 5 沒共識），重要的是序位一致性。

### Bake-off 候選池

`gpt-5-nano` / `gemini-2.5-flash-lite` ⭐ / `gpt-4o-mini` / `claude-haiku-4-5`（價格依 2026-05-05 Zeabur AI Hub 牌價）。`gpt-4o` 只當 quarterly cross-check baseline。預期 flash-lite 中文 judge OK 且最便宜（~$0.32 per run）→ 首選 production judge。

### Golden set 結構：JSON 檔，per show 一檔

```json
{
  "show_slug": "this-not-that-cool",
  "show_id": "uuid-or-id",
  "version": "v1",
  "created_at": "2026-05-05",
  "items": [
    {
      "id": "tntc-001",
      "type": "fact" | "comprehension" | "cross-episode" | "negative" | "code-switch",
      "question": "...",
      "expected_answer_keywords": ["..."],
      "ground_truth_chunk_ids": ["ep:<uuid>@<start_time>"],
      "sentinel": false,
      "source_episode_id": "<uuid>"
    }
  ]
}
```

`expected_answer_keywords` 給 Recall on answer text（不用 LLM judge 也能粗略估）；`ground_truth_chunk_ids` 對應現有 `ep:<episode_id>@<start_time>` 同一 chunk_id 慣例（與 R1.1 events 表 + RAG citation 一致）。

### Recall@5 與 MRR 計算

Recall@5：`|relevant ∩ top5| / |relevant|` 取每題平均。若 ground_truth 多個 chunk，top5 命中任一就部分 recall。

MRR：`mean(1/rank_of_first_relevant)`，找不到記 0。

純 numpy 實作；不引第三方（trec_eval 太重）。

### Eval runner 直接打本地 backend

`backend/eval/run.py` 預期 backend 已起在 `localhost:8000`（dev），用 admin session token（從 env 或 e2e backdoor 拿）打 `/shows/{id}/query` 取得 answer + sources，再算 4 個指標。

替代方案 — 把 RAG 服務 import 進 process 直接呼叫。Reject：偏離 production code path，且 LLM 設定（answer step）要從 DB 讀，整個 boot 起來很重，不如打 HTTP。

### CI 策略：nightly only on main

`.github/workflows/eval.yml` 不在 PR 上跑（成本 + 速度），只在 main 上 cron `0 3 * * *`（UTC 03:00 = 台北 11:00 早上）+ `workflow_dispatch`。runner 起 backend Docker compose（沿用 prod 同 entrypoint）跑 eval。失敗 report-only，不寫 status check。

替代方案 — Zeabur Cron Job 服務跑。Reject：CI artifact 還是要進 GitHub，不如直接在 GH Actions 跑。

### Skill 半自動流程

skill 的工作流：
1. 接 show_id + N + 模式
2. 從 episodes 表抽 5 集 transcript chunks（隨機抽，多元覆蓋）
3. LLM 合成題目（按題型分佈），帶 source chunk_id 給 LLM
4. LLM 反向標 ground_truth_chunk_ids（語意比對）
5. 輸出未稽核草稿 + 分批呈現給使用者抽審 5 題（ groupy by type）
6. 使用者拍板後寫入 JSON

Sentinel 10 題不交給 LLM，使用者手作（skill 引導）。

### 路線 B 提醒：用 Celery beat

每月 1 號 03:00 UTC 跑 `golden_set_reminder` task，掃每個 show 的最新 dataset JSON `created_at` 與該 show 期間新增集數。觸發條件：`(now - created_at) > 30 days AND new_episodes >= 10`。寄信走 ZSend。

## Risks / Trade-offs

- [Mini-set 20 題對人工標分太重] → 限制 30 分鐘內標完，第一輪可只標關鍵 10 題
- [judge LLM 對中文音樂/嘻哈領域 jargon 可能誤判] → sentinel 題保留，每 quarter 用 gpt-4o 重 sample 5 題人工 audit
- [DeepEval AnswerRelevancyMetric 用反向 LLM 出 question 算 cosine — embedding 走 OpenAI 還是 hub？] → embedding 永遠走 OpenAI 官方（per `feedback_secrets_in_env.md`），DeepEval 預設能設 base_url 到 OpenAI
- [CI 跑 backend 起得起來嗎] → 用 docker compose；不行就改 host pip + uvicorn + 連測試 DB（Postgres service container in GH Actions）
- [Golden set chunk_id 與 prod chunk_id drift] → chunk_id pattern `ep:<episode_id>@<start_time>` 是穩定的（不隨 chunking 演算法重跑改變）；若未來改 chunk 邊界 → 重新標 sentinel 即可，core 自動失效
- [Skill 全自動產的題目品質] → 用範例 few-shot prompt + 強制要求每題寫 source_episode_id；使用者抽審 5 題擋低品質；Spearman 上線後若 baseline metric 異常低就重審

## Migration Plan

1. PR 1（本 change）：proposal + design + specs + tasks（park）
2. Apply 階段 stage A（session 1）：bake-off + golden set 50 題
3. Apply 階段 stage B（session 2）：framework 骨架 + CI + skill + reminder
4. Manual 觸發第一次 nightly 跑，確認 JSON 報告產出 OK
5. R3 / R2 / R4 開始時必跑 eval 對比 baseline

Rollback：純加性，整目錄 `backend/eval/` 直接砍即可；新 endpoint `/admin/golden-set-status` 移除；beat task 停。

## Open Questions

無 — 議程結論已對齊，candidate / N / 切片方式都定了。
