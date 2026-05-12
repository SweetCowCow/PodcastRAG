## Context

R3.2 的 two-layer retrieval + topic seg backfill 跑完後，2026-05-11 量到 episode-level Recall@5 = 0.1548，遠低於設計 target ≥ 0.35。第一輪歸因（routing 為兇手）已用 `ENABLE_TWO_LAYER_ROUTING=false` hotfix 完整 48 題 eval 證偽 — flag on / off 兩組 Recall@5 都是 0.1548。Hotfix flag 已從 prod 拔回，code 路徑無副作用。

剩下 5 個候選真兇假設（在 spectra-discuss 階段已逐一驗證可能性 + 案例證據），按可能性與成本排序：

| # | 假設 | 證據 | 修法成本 |
|---|---|---|---|
| 1 | `DESCRIPTION_CAP=3` 把 top-5 灌滿 desc hits 擠掉正確 transcript chunk | canary 觀察：q01 top-5 = 3 個 desc(@0.00) + 2 個 transcript hits 全來自錯誤 episode | 改常數，秒級 |
| 2 | `show-name terms filter` 把含 show-name 的 query lexical 信號掏空 | DB 證實 `這又沒有很屌` `is_show_name=true`；q01 lexical 側被 strip | 改常數，秒級 |
| 3 | Description embedding 顆粒太粗（每集 1 chunk） | 每集 desc 1 chunk 把贊助讀稿 + 摘要 + 重點 bullet 都平均化進去 | 細切 + re-embed backfill，30 分鐘 + ≤ $3 |
| 4 | embedding model `text-embedding-3-small` 對中文短語辨識弱 | code-switch 類 3/3 全 0% recall；fact 類 17.6% 偏低 | 換 model + re-embed 全 414 集，數小時 + ≤ $30 — **不屬本 change scope** |
| 5 | RRF 融合不對稱（transcript / description 各 RRF score 直接 sort） | code 結構問題，retrieve_hybrid 內 sort merge 沒做 source-aware reweight | 重構 RRF 融合，半天 — **本 change Case D 才動** |

候選 #1、#2 是「動 default constant」級別，先做 lever test 篩；候選 #3 需要 backfill；#4 顯著超出 R3.x scope（另立 change）；#5 是結構問題，視 Case D 結果決定。

## Goals / Non-Goals

**Goals:**

- 把 R3.2 episode-level Recall@5 從 0.1548 拉到 ≥ 0.35（過 R3.2 設計 gate）
- 用 lever test 篩出真兇 → 寫進 design.md evidence section 留下實證紀錄
- 與 `r3-2-two-layer-topic-seg` 同一 R3.2 milestone 一起 archive

**Non-Goals:**

- 不換 embedding model（候選 #4 — 留待 `r3-4-embedding-model-swap` 提案）
- 不動 two-layer routing 邏輯（已證偽，flag 機制留著但 default 行為照常）
- 不做 RRF 融合重構（候選 #5 — Case D 才回頭，且傾向另立 change）
- 不擴 golden set / 不換 judge model（R1.3 範疇）
- 不動 R3.3 metadata filter

## Decisions

### D1 — 兩段式：lever test 先、根因解隨後

寧可花 30 分鐘跑 4 組 eval（總成本 ≈ $2 judge），也不要從 5 個候選裡猜真兇。lever test 是「結構性 disconfirmation」：證偽幾個就能把假設池砍掉一大半，剩下的才值得投資修。

### D2 — 用 env flag 短路 default，避免動 code 主邏輯

加 `RAG_DESCRIPTION_CAP`（int，預設讀 `DESCRIPTION_CAP=3`）與 `RAG_SHOW_NAME_FILTER`（bool，預設 true）兩個 env 旗標。`rag.py` 在 module load 時讀一次 env，不在每次 query 都呼叫 `os.getenv`（性能 + 可預測）。

Phase 2 完成後依結果改 hardcoded default，env flag 機制保留但變成 admin-tooling（譬如以後想 A/B 測時還能用）。

### D3 — Case 分支判斷的數值門檻

| Case | 條件 | 行動 |
|---|---|---|
| A | lever (b) 或 (c) 任一組 episode Recall@5 ≥ 0.35 | 改該常數 default；ship；archive |
| B | (d) ≥ 0.35 但 (b) (c) 都沒過 | 兩個常數 default 都調；ship；archive |
| C | (d) < 0.35 但 Δ vs (a) > 0.05 | 觸發 description re-chunking（每段 ≤ 200 chars）+ re-embed backfill；再跑 final eval；若 ≥ 0.35 ship + archive |
| D | Case C 仍 < 0.35 | 本 change 收尾紀錄結果，建議下一張 change（embedding swap 或 RRF 重構），R3.2 milestone 暫不 archive |

### D4 — Final eval 必走 v2.0 6 phase

過 gate 那一輪 eval 必須走 `rag-eval-runner` skill v2.0 的完整 6 phase（preflight / canary 3 / metric-sanity / variance 3 runs / checkpoint / persistent runner），不可單跑一次拿單一數字宣稱 ship — 沿用 R2.1 archive RCA 教訓。

### D5 — 用 episode-level metric 當主 gate

R3.2 design 已預設 `--metric-level episode`。本 change 沿用，chunk-level 只當 sanity check（不當 gate）。理由：episode-level 對「retrieved 與 anchor 同 episode 即算 hit」更貼近使用者實際體驗（看到對的集就贏一半）。

## Implementation Contract

### Behavior

- 設 `RAG_DESCRIPTION_CAP=N`（N ≥ 0 整數）→ `retrieve_hybrid` 中 description hits 最多 N 個進 top-K；N=0 代表完全排除 description hits
- 未設 / 設無效值 → 退回 hardcoded `DESCRIPTION_CAP=3`（Phase 2 後 default 可能改）
- 設 `RAG_SHOW_NAME_FILTER=false` → `_build_ts_query` 不再 drop `tokenizer.get_show_name_terms()` 之中的 token
- 未設 / 任何其他值 → 維持目前 strip 行為
- Embedding side（語意 cosine）行為不受影響 — 不論 flag 如何都拿完整 question 算 embedding

### Interface / Data Shape

- 兩個 env flag 都讀於 module import 時，存進 `_DESCRIPTION_CAP_RUNTIME: int`、`_SHOW_NAME_FILTER_ENABLED: bool` module-level binding
- 不暴露 admin UI 或 REST endpoint — 純 ops env，重啟 service 才生效
- Eval runner 不需改（已支援透過 prod backend 跑）

### Failure Modes

- 環境變數值無法 parse（譬如 `RAG_DESCRIPTION_CAP=abc`）→ 日誌警告一行（stderr），fall back 到 hardcoded default
- 不會 raise 例外阻擋啟動

### Acceptance Criteria

- 新增單元測試 `backend/tests/test_rag_retrieval_flags.py` 涵蓋：
  - `RAG_DESCRIPTION_CAP=0` 時 retrieve_hybrid 返回的 hits 沒有 `source == "description"` 任何一個
  - `RAG_DESCRIPTION_CAP=2` 時 source==description 的 hits ≤ 2
  - `RAG_DESCRIPTION_CAP` 未設時行為等同現狀（hardcoded 3）
  - `RAG_SHOW_NAME_FILTER=false` 時 `_build_ts_query("迪拉「這又沒有很屌」")` 結果含 `這又沒有很屌`
  - `RAG_SHOW_NAME_FILTER` 未設時 `_build_ts_query` 不含 `這又沒有很屌`（沿用現狀）
- Phase 1 lever test 4 組 eval JSON / MD 全部歸檔於 `backend/eval/results/`，檔名含時間戳
- 4 組 delta 表格寫進本 design.md 對應 evidence section（implementation 時補）+ append 進 `docs/case-studies/r32-routing-regression-2026-05-11.md`
- Final eval pass：episode-level Recall@5 ≥ 0.35、SD ≤ 0.05（3 次 variance run 的 mean SD）

### Scope Boundaries

**In scope：**

- 加 2 個 env flag + 對應單元測試
- 跑 Phase 1 4 組 lever eval（48 題 each）
- 依 Case A / B / C 改 default 或加 description re-chunking
- 跑 Phase 2 final eval（含 v2.0 6 phase）
- 更新 case study、release log

**Out of scope：**

- 換 embedding model（候選 #4）
- 重構 RRF 融合（候選 #5）
- 修改 routing 邏輯（已證偽，沿用 R3.2 現有 flag-controlled 路徑）
- 動 golden set / judge model

## Risks / Trade-offs

| 風險 | 嚴重性 | 緩解 |
|---|---|---|
| Phase 1 lever 4 組都沒拉動 Recall（Case D） | 中 | 已寫進 Decision D3 — 本 change 收尾紀錄結果，不勉強 ship；另開 change 處理 embedding swap |
| description re-chunking backfill 把資料庫狀態弄亂 | 中 | re-chunk 跑 staging 一集驗證 → 全量前先做 idempotency 驗證；舊 chunk 留著直到新 chunk 完成 + eval pass 才刪 |
| 改 `DESCRIPTION_CAP=0` 後使用者看不到節目簡介來的命中 | 低 | 業務面：節目簡介當「次選 source」是 R2.1 設計初衷，但若它擠掉正確 transcript hit 反而傷使用者；trade-off 接受 |
| env flag 機制在 Phase 2 之後留著沒人用 | 低 | 不刪；明文 comment 標「ops-tuning，未來 A/B 用」 |
| Final eval pass 後使用者體驗仍不直觀有改善 | 中 | Recall@5 是內部代理 metric，使用者體驗要 qa_feedback（R1.3）才看得到 — 本 change 結果寫進 release log 同時提醒 user 留意 feedback signal |

## Phase 1 Evidence — lever test 4-arm 結果（2026-05-12）

4 組 eval 全在 prod backend 跑完，golden set v2 (48 題)，judge gpt-5-nano，top_k=5。

| Arm | Env | Recall@5 | MRR | Judge mean | 結果檔 |
|---|---|---|---|---|---|
| (a) baseline | 預設 | 0.1548 | 0.0833 | 0.4229 | `eval-this-not-that-cool-20260511T045209Z` |
| (b) CAP=0 | `RAG_DESCRIPTION_CAP=0` | 0.1548 | 0.1524 | **0.6292** | `eval-this-not-that-cool-20260511T091914Z` |
| (c) FILTER=false | `RAG_SHOW_NAME_FILTER=false` | 0.1548 | 0.1298 | 0.5646 | `eval-this-not-that-cool-20260511T093831Z` |
| (d) both | CAP=0 + FILTER=false | 0.1548 | 0.1524 | **0.6292** | `eval-this-not-that-cool-20260512T011020Z` |

### 觀察

1. **Recall@5 四組同分 0.1548** — embedding + lexical hybrid 對描述短句 / 中英 code-switch 有結構性 ceiling，動 default constant 拉不動 episode-level recall
2. **(d) 完全等於 (b)** — `SHOW_NAME_FILTER=false` 在 `CAP=0` 之上是 no-op；CAP=0 已把 description hits 全擋，filter 本來就沒東西可過
3. **(b) Judge 0.42 → 0.63（+0.21）** — description 雜訊（贊助讀稿 / show notes / 來賓介紹）擠進 LLM context 確實污染答案；CAP=0 讓 LLM 拿到乾淨 transcript chunks 後品質顯著提升
4. **(c) Judge 0.42 → 0.56（+0.14）但 MRR 不如 (b)** — show-name filter 拿掉只能搶救 lexical 側部分 query，無法解決 description 雜訊主因

### Case 判定：**Case C**

依 D3 判斷：(d) Recall@5 = 0.1548 < 0.35（gate），但 Δ vs (a) = 0 — 觸發 Case C：description re-chunking。

### Ship 項判定

- ✅ `RAG_DESCRIPTION_CAP=0` 寫成 production default（Judge 顯著拉升，無爭議）
- ❌ `RAG_SHOW_NAME_FILTER=false` 不 ship（在 CAP=0 之上 no-op）
- ⚠️ Recall@5 0.1548 仍未過 R3.2 gate ≥ 0.35 → Phase 2 必須跑 description re-chunking

## Phase 2 Plan — Staged Single-Show Rollout（Case C）

為避免「表現未穩定時對全 corpus 燒錢」，Phase 2 re-chunking + re-embed 採**單節目 pilot → 驗證 → rollout 其他節目**。

### Pilot 對象：「這又沒有很屌」

| 項目 | 值 |
|---|---|
| show_id | `45fc2462-17cf-42f5-98a7-68fe1a222228` |
| 轉錄完成度 | 163/163 集（100%）|
| Golden set | ✅ 已有 v2 (48 題) — Phase 1 (a)(b)(c)(d) 都基於它 |
| 估計成本 | re-embed ≤ $15 USD（OpenAI 官方） |
| 估計時間 | ~1–2 hr worker |

選此節目原因：(1) 全 transcribe 完整，無集數缺漏雜訊 (2) 唯一有客觀 eval 數據比對 (3) Phase 1 四組 lever 都是基於它，數據連貫。

### Rollout 階梯

| 階段 | 動作 | Gate | Cost 估算 |
|---|---|---|---|
| 1. Pilot | re-chunk + re-embed「這又沒有很屌」description chunks（每段 ≤ 200 chars）| Phase 1 (b)+pilot final eval Recall@5 ≥ 0.35 + Judge ≥ 0.60 | ≤ $15 |
| 2. Hold & observe | 其他 2 show（曼報 / 壹加壹電台）暫不動 | 體感 + 不退步 | $0 |
| 3. Rollout #2 | re-chunk「曼報」（轉錄完成度 139/140）| sentinel + 體感 | ~$8 |
| 4. Rollout #3 | re-chunk「壹加壹電台」（先等它轉錄完整）| 同上 | ~$8 |

### Rollback Plan

- 舊 description chunks 在 re-embed 完 + eval pass 前**保留不動**（D5 sub-decision）
- Pilot 失敗 → 把舊 chunks 切回 active（不重 transcribe，純 metadata flip）
- 其他 2 show 沒動過 = 0 風險

### Chunking 版本共存（重要）

新切的 description chunks 帶 `chunking_version=2`，舊的維持 `v1`。retrieval pool 同時讀新舊版本到 Phase 2 收尾。Phase 3 確認 v2 全 show rollout 完才刪 v1。詳見另立 change `chunking-version-coexistence`（Phase 2 啟動前 propose）。

### Cost / Approval Discipline

- Pilot ($15) 在「pilot < $20 免問」紀律之內（`feedback_cost_awareness.md`），可直接執行
- Rollout #2 / #3 累計超過 $30 → 每階段執行前先報 cost + ETA 等使用者 confirm

## 變更歷史

- 2026-05-11 propose 階段：spectra-discuss 5 個假設、確認 routing 已證偽、lever test 兩段式設計定稿
- 2026-05-12 Phase 1 完成：4-arm lever test 全跑完，Recall 結構性 ceiling 證實 → Case C；Phase 2 staged single-show rollout 計畫定稿（pilot 對象「這又沒有很屌」）
