## Why

eval-framework-upgrade（2026-05-30 archive）已 ship 雙寫架構：Langfuse Cloud 收即時 trace、PG `eval_traces` 表收長期歸檔。但「runner → backend → PG」這條管線最後一段沒接通——eval runner 走 HTTP `/query?debug_trace=true` 打 backend，backend 無法得知 caller 是「哪個 eval run 的第幾題第幾輪」，導致 `span_writer.write_span()` 因 `eval_context` ContextVar = `None` 而 skip 寫 PG。後果：

1. `eval_traces.run_id` / `item_id` / `turn_idx` 三欄全部空白，跨 run SQL 比對（譬如 `WHERE item_id='b20' AND run_id IN (old, new)` 比對 prompt-fingerprint 漂移）無法執行
2. `prompt_fingerprint_diff.py` 預留的 `--source=sql` 路徑目前被迫退回 inline HTTP 萃取
3. Tier 1 b20 chunk-level RCA、Tier 2 BM25 / IDF / Voyage tune 全部需要這條 SQL RCA flow 才能高效 verify

## What Changes

- eval runner v2 (`run_chat_agent_eval_v2.py`) 跑前 generate 一個 `run_id` 字串，每送一 turn 注入 3 個 HTTP header：`X-Eval-Run-Id` / `X-Eval-Item-Id` / `X-Eval-Turn-Idx`
- backend `/query` endpoint 加 FastAPI dependency `bind_eval_context()`：當 caller 為 admin role 且帶 3 個 header 時呼叫 `set_eval_context()`，request 結束時 `reset_eval_context()`；非 admin 帶 header 靜默 ignore
- runner 把 `run_id` 寫進 result JSON 檔頭、方便事後用 `run_id` 跑 SQL
- 新增 SQL RCA demo script `backend/eval/scripts/sql_rca_demo.py`，跑 calibration_8 一輪後示範三條 SQL（per-turn span count / 跨 run search_query diff / per-turn tool timeline），證明 plumbing 通了
- `prompt_fingerprint_diff.py` 接通 `--source=sql --run-id-old=... --run-id-new=...` 路徑

## Non-Goals

- v1 runner (`run_chat_agent_eval.py`，schema_version=1 legacy path) 不動，繼續走 inline-extract 路徑
- 不新增 PG 欄位（schema 在 `b6c7d8e9f0a1_add_eval_traces.py` 已就位）
- 不改 Langfuse Cloud `@observe` 上傳路徑（metadata 注入已在 `agent.py:317-324` 就位）
- 不做「Cloud → PG 補拉」reconcile script（屬未來 follow-up，不在 scope）
- 不對 prod user 流量寫 PG（ContextVar 預設 None → write_span skip，per design Decision 1a/7）

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `rag-eval-runner`: 新增「eval runner 跑前 SHALL generate run_id 並注入 X-Eval-* 三個 header」要求
- `eval-observability`: 新增「PG eval_traces 對 runner-driven request SHALL 寫滿 run_id / item_id / turn_idx」要求；admin debug gate 行為延伸到三個 header

## Impact

- Affected specs:
  - `rag-eval-runner`（MODIFIED：runner 注入 header + 生成 run_id）
  - `eval-observability`（MODIFIED：PG sink 對 runner 流量 SHALL 填滿 dataset locator）
- Affected code:
  - Modified:
    - backend/scripts/run_chat_agent_eval_v2.py（runner 加 run_id 生成 + header 注入 + result JSON 落 run_id）
    - backend/app/api/query.py（`/query` endpoint 加 `bind_eval_context` dependency）
    - backend/eval/scripts/prompt_fingerprint_diff.py（接通 `--source=sql` 路徑）
  - New:
    - backend/app/api/deps.py（新增 `bind_eval_context()` dependency；若檔案不存在則建立、若已存在則 append）
    - backend/eval/scripts/sql_rca_demo.py（SQL RCA flow demo + verify）
    - backend/tests/test_eval_context_dependency.py（unit test：admin honor / non-admin silent ignore / missing header skip）
