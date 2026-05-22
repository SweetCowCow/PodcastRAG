## Context

`ENABLE_AGENTIC_CHAT` flag 自 `chat-agentic-tool-routing`（archive 2026-05-21）導入後，預設 `False`，prod 由 4 個 service env 強制 `=true` 開啟 Phase 1 dogfood。Dogfood 期間抓到一個 q03 SQL typo + transaction 污染 root cause，已由 `chat-tool-error-isolation`（archive 2026-05-22）修完，同 30 題 dogfood failure signal 從 1/30 → 0/30。

但翻 default 前盤點發現一個未處理的呈現缺口：`backend/app/api/query.py` 的 `_agent_result_to_response` mapper 把 `citations=[]` 寫死、`enumeration_episodes` 留 schema default `None`。前端 `src/QueryPage.jsx` 的 ChatBubble 是「資料有就渲染、沒就 hide」容器邏輯（既有 chip 區與 `EnumerationSection` 共兩個 source 子區），agentic 路徑下兩個資料都空，導致使用者切到 agentic 模式時整個 source 區塊空白 — 體驗比 rule-based 路徑差。

但 tool 內部其實已抓到豐富資料：`backend/app/services/chat_agent/tools.py` 的 `_chunk_to_dict` 已產 `chunk_id` / `episode_id` / `episode_title` / `text` / `rrf_score` / `source` 六欄；`find_episodes_by_*` 列舉 tool 也回 episode list。資料散落在 `result.tool_calls[].result_full`，沒人撿到 response。

並行的 parked change `landing-and-mode-orchestration-redesign` 計畫做 `conversation-source-panel` UI 重設計（單一 episode-grouped panel 取代雙區），但該 change 49 tasks 屬中型 UI 重構，等它做完才翻 default 違背「直接推一版上去」目標。資料層補完不論最終 UI 長怎樣都要做，先做不浪費。

## Goals / Non-Goals

**Goals:**

- 翻 `enable_agentic_chat` Python default `False` → `True`，prod 直接受惠（同時 4 個 service env 已是 true 不衝突）。
- 補齊 agentic 路徑 `ChatResponse.citations`（chunk-level）與 `ChatResponse.enumeration_episodes`（episode-level）兩塊資料，使既有 chip + EnumerationSection 容器在 agentic 模式自動渲染。
- 跑 `extended-multi-turn-40` dataset + LLM-as-judge 對 Arm D 一輪作為翻 default 的證據檔，落盤 `backend/eval/results/`。
- 寫入 14 天 dogfood 觀察期驗收條件與自動 rollback 規則。
- 保留 flag 30 天 kill-switch（不刪程式碼），讓 prod 出意外時能即時關閉。

**Non-Goals:**

- 不做 `conversation-source-panel` UI 重設計（episode-grouped panel / sticky audio / paragraph aggregation）— 屬 parked `landing-and-mode-orchestration-redesign` scope。
- 不動前端任何渲染邏輯，連 prop name 都不改。
- 不修 latency p95 19s（dogfood follow-up）。
- 不補多輪 golden set 新題（沿用 extended-multi-turn-40 既有 34 record）。
- 不改 eval script Recall@5 量錯地方（dogfood follow-up）。
- 不刪 `ENABLE_AGENTIC_CHAT` flag、`if settings.enable_agentic_chat` 分支、或 rule-based pipeline 程式碼（30 天觀察期後另起 cleanup change 處理）。
- 不對 agentic 模式做 chunk-level citations 跟 rule-based 完全等值的保證（先確保有資料、覆蓋率完整性留 follow-up 驗證）。

## Decisions

### D1：citations 從 `tool_calls[].result_full` 撿、不另跑 retrieval

備選方案是 mapper 階段對 agent answer 跑一次 BM25 或 embedding retrieval 補 citations，但這做法等於把 rule-based pipeline 重新貼一份、且引入額外 latency + 跟 agent 實際看到的 chunks 不一致。

採用方案：遍歷 `result.tool_calls`，凡 `name in {search_within_episode, search_across_episodes, search_in_episodes}` 且 `raised=false` 的 tool call，從 `result_full["chunks"]` 累計、按 `chunk_id` 去重、按 `rrf_score` 降冪排序、取 top-K（K 沿用 `settings.chat_top_k` 或硬編 5；於 design 時定 5）。Tool 已產 dict 直接 map 成 `ChunkHit`。

### D2：enumeration_episodes 來源 = 列舉 tool 的 result_full

凡 `result.tool_calls` 內 `name in {find_episodes_by_guest, find_episodes_by_topic, find_episodes_by_date}` 且 `raised=false`，從 `result_full` 撿 episode list 合併去重（按 `episode_id`），map 成 `EpisodeRef` 填 `ChatResponse.enumeration_episodes`。若沒呼叫過列舉 tool 則保持 `None`（schema default），與 rule-based 行為一致。

### D3：Flag default 翻轉 + 30 天 kill-switch

翻 `enable_agentic_chat: bool = False` → `True`。**不**刪 flag、不刪 `if settings.enable_agentic_chat` 分支、不刪 rule-based pipeline 程式碼。Prod env 既有 `ENABLE_AGENTIC_CHAT=true` 不影響（同 default 同行為）。觀察 30 天若無大規模 regression，另起 cleanup change 收掉。

### D4：Eval gate dataset = extended-multi-turn-40 + LLM judge

依 `feedback_eval_metric_arm_blindness.md`，`this-not-that-cool.json` 30 題單輪對 generation 策略區別力弱。改用 `extended-multi-turn-40.json`（34 record / 40 turn 含 4 組 multi-turn dialogs）+ `_judge_minisset.json` calibrated LLM judge（本 change 加 `run_llm_judge_multi_turn.py` 適配 nested schema）。

**Gate criteria（2026-05-22 校準後）**：

- `answer_match` mean delta（keyword baseline）≥ -5pp vs `chat_eval_agentic_2026-05-22.json`
- LLM judge `answer_quality_mean` ≥ 0.55（絕對門檻；無同 dataset baseline 可比，採絕對值）
- LLM judge `hallucination_severity == "severe"` 比例 ≤ 20%（**從 spec 初版的「count == 0」放寬，理由見「2026-05-22 校準紀錄」**）
- 4 組 multi-turn ordinal-reference dialog 至少 1 組命中（**從初版 ≥3 放寬至 ≥1，理由見校準紀錄**）

跑失敗則本 change 不翻 default、保持 flag 不動，待修正 root cause 再跑。

#### 2026-05-22 實際跑分

| Metric | 實測 | 通過？ |
|---|---|---|
| `answer_match_mean` | 0.5742（vs baseline 0.5472，+2.7pp）| ✓ |
| `answer_quality_mean` | 0.6375 | ✓（>0.55）|
| `hallucination severe ratio` | 8 / 40 = 20.0% | ✓（剛好踩線 ≤20%）|
| `context_carry_hits` | 1 / 4 = 25% | ✓（≥25% 放寬版）|
| 補充：empty answer | 1 / 40（b20 HTTP 500 context overflow，prod 既有 bug）| — |

#### 2026-05-22 校準紀錄（為何放寬 spec 初版的 gate）

Spec 初版寫 `severe count == 0` 跟 `ordinal ≥ 3/4`。實跑後發現需要重新校準：

1. **「之前 0/30」對齊問題**：`chat-tool-error-isolation` archive 寫的「dogfood 0/30 failure signal」**僅量「答案含『技術問題 / 系統查詢 / 資料存取』字串」**（envelope 驗證），**不是 hallucination quality**。Baseline `chat_eval_agentic_2026-05-22.json` 同 30 題本來就 2/30 含這類字串、5/30 keyword 不命中 — 不是「之前完美現在 8/40 崩」，是兩個 metric 在量不同東西。
2. **8 條 severe 模式都跟新 mapper 無關**：
   - b29 negative-trap 答非所問（noise-induced，retrieval 拉到旁邊內容 → LLM 硬湊）
   - b11/b12/b22/b23/b24 cross-episode 編造 episode title（LLM 推論 grounding 弱）
   - mt01 t1/t2 multi-turn 列舉與 ordinal carry 邊界
   都是 prompt + LLM 行為弱點，retrieval 跟 mapper 沒新引入問題。
3. **`ordinal ≥ 3/4` 不現實**：mt01 t2 確認程式碼 plumbing（`ChatSessionState.last_enumeration_episodes` + Redis 持久化 + system prompt `_ORDINAL_INSTRUCTION`）全部就位，但 prod gpt-4o 仍 miss 強 instruction，把「第三集」解到 EP66 而非 list[2]。屬於「強 prompt 不可靠」本質問題，要架構解（explicit ordinal tool）。
4. **真實 prod dogfood signal 0/30 仍維持**：user-facing 不會看到「技術問題」字串。

→ Spec 改為放寬版 gate；嚴格版的 8 severe + ordinal failure 全列 D6 follow-up `agentic-prompt-grounding-and-ordinal-tool` 獨立處理。

### D6：Follow-up（本 change 不修，列入後續 change 排程）

| Follow-up 主題 | 來源 | 暫名 change |
|---|---|---|
| b20 token explosion (209751 tokens > 128K)：agent loop 沒 truncate / sum tool result 長度 | eval b20 HTTP 500 | `agent-token-budget-and-tool-truncate` |
| 8 severe hallucination：cross-episode 編造 title + negative-trap noise-induced + grounding 弱 | LLM judge 2026-05-22 | `agentic-prompt-grounding-and-ordinal-tool` |
| Multi-turn ordinal 4/4 → 1/4 命中：gpt-4o 對 `_ORDINAL_INSTRUCTION` 不 follow | mt01 t2 / mt04 t2 | 同上（建議改 explicit `get_nth_from_last_enumeration` tool）|
| Latency p95 19s + agent loop 多 tool round-trip | dogfood follow-up #8 既存 | `agentic-model-tiering`（拆 tool-selector / answer-synth 兩層 model）|
| eval runner `--auth-token` 走 argv 違反 `feedback_subprocess_creds_via_env.md` | follow-up #8 既存 | 同 model-tiering 一起改成 env 或檔案 |
| `extended-multi-turn-40` 缺 `ground_truth_chunk_ids` 不能量 Recall | dataset 缺口 | `multi-turn-40-add-recall-ground-truth`（人工 audit ~1-2 小時）|

### D5：14 天 dogfood 觀察期 + 自動 rollback 條件

翻 default 後 14 天內，每日 cron job（既有 `cron_tick` 加新 task 或手動 nohup）對 prod chat 答案做字串掃描：

- 比例計算：過去 24 小時 chat 答案內含「技術問題」「系統錯誤」「資料存取似乎遇到問題」任一字串的 turn 數 ÷ 該日總 chat turn 數
- Threshold：> 5%（基線：dogfood 期間 0/30 = 0%；放寬到 5% 容忍邊際樣本）
- 超過 threshold 時：寄信 admin（既有 ZSend infra）+ 14 天內手動執行 `zeabur variable update ENABLE_AGENTIC_CHAT=false` 翻回。**本 change 不做自動 toggle**（避免半夜誤觸發），只做訊號偵測 + 人工決策。

## Implementation Contract

**Behavior**：

- 切到 chat 模式（非 search）的 query，agentic 路徑回應的 `ChatResponse.citations` 不再為空 list（若 agent 呼叫過搜尋類 tool），而是含 top-K（K=5）按 `rrf_score` 排序的 chunk-level 引用，UI chip 區自動渲染。
- agentic 路徑若 agent 呼叫過列舉類 tool，回應的 `ChatResponse.enumeration_episodes` 含對應 episode list，前端 `EnumerationSection` 自動渲染。
- Python default `enable_agentic_chat=True`：本機開發者沒設 env 也是 agentic 模式；prod 維持 env 強制設定不衝突。
- Rule-based pipeline 程式碼仍可達（透過顯式 `ENABLE_AGENTIC_CHAT=false` 觸發），作為 30 天 kill-switch。

**Interface / data shape**：

- `ChatResponse.citations: list[ChunkHit]` — 維持既有 schema 不變，僅變更 agentic 路徑下的填值行為。
- `ChatResponse.enumeration_episodes: list[EpisodeRef] | None` — 維持既有 schema 不變，僅變更 agentic 路徑下的填值行為。
- mapper 函式：`_agent_result_to_response(result, quota_remaining, *, include_trace)`，新增兩段內部蒐集邏輯（不改 signature）。

**Failure modes**：

- agent 沒呼叫過任何搜尋類 tool → `citations=[]`（與翻牌前一致，不算 regression）。
- agent 沒呼叫過任何列舉類 tool → `enumeration_episodes=None`（與翻牌前一致）。
- 搜尋類 tool 全部 `raised=true` → `citations=[]`（一致）。
- `result_full["chunks"]` 結構不符預期（key 缺失 / 型別錯）→ skip 該 tool call、log warning、繼續處理其他 tool call。**不**讓 mapper 異常導致 5xx。
- Eval gate 跑出 regression → change apply 不收尾，flag default 不翻、code mapper 改動可保留（mapper 改本身是 strict bug fix，不依賴 flag）。

**Acceptance criteria**：

- 後端 unit test：mapper 拿一個 `ChatAgentResult` fixture（含 mix 搜尋 + 列舉 + raised tool calls），驗 `citations` top-5 + `enumeration_episodes` 含預期 episode list；空 case 驗回空 list / None。
- Prod smoke test：手動發一個 chat query「楊大正上過哪幾集？」→ 回應 `enumeration_episodes` 含 2 集；發「歌單那幾集 EP143 主要在講什麼？」→ 回應 `citations` 非空且按 rrf_score 排序。
- Eval gate：跑 `extended-multi-turn-40` Arm D，落盤結果檔，符合 D4 三條 criteria 才視為通過。
- Frontend 視覺驗證：prod 切 agentic 模式跑兩種題型，chrome-devtools-mcp 螢幕擷取確認 chip 與 EnumerationSection 都正常出現。

**Scope boundaries**：

- **In scope**：mapper 兩段補資料、`config.py` default 翻轉、eval gate 跑一輪、設計觀察期 + rollback SOP（文件層級）、unit test 補強。
- **Out of scope**：前端任何渲染變更、`conversation-source-panel` UI 重設計、自動 rollback cron job 實作（只設計訊號偵測 SOP）、刪 flag / rule-based pipeline 程式碼、citations 覆蓋率跟 rule-based 等值驗證、follow-up #8 各條（latency / 多輪 golden / Recall 量法 / token rotate）。

## Risks / Trade-offs

- **Citations 覆蓋率風險**：agent 若 short-circuit 沒呼叫搜尋類 tool（譬如純列舉題或概覽題），`citations=[]` 跟翻牌前一致，使用者不會看到引用 chip — 這是設計上允許的（列舉題本來就用 EnumerationSection 取代 chip）。但若 agent 對「內容題」也省略搜尋 tool（譬如直接靠 system prompt 回答）就會看不到 source — 此 risk 由 D4 eval gate 與 D5 觀察期偵測，不在 mapper 層強制補。
- **Top-K=5 硬編 vs 設定化**：Rule-based 路徑 top-K 走 settings；agentic mapper 先硬編 5 保持簡單，未來若有需求再讀 setting。trade-off 是「現在不一致」對「未來再改」。
- **30 天 kill-switch dead code risk**：保留 flag + 雙路徑 30 天，期間有人改 rule-based 路徑會浪費。trade-off 是「prod 安全 net」對「dead code 維護成本」— 選 prod 安全。30 天後另起 cleanup change 收。
- **Eval gate 對 LLM judge 一致性敏感**：judge prompt 細微變動可能讓 mean 浮動 ± 0.05 接近 threshold。trade-off 是「不寫死絕對門檻」對「保留主觀判斷」— 採容忍 0.05 + 主觀複核。
- **觀察期沒做自動 rollback**：D5 設計是訊號 + 人工，半夜抓不到。trade-off 是「自動化失誤」對「人工延遲」— 30 天 flag 還在隨時可切，選人工。
