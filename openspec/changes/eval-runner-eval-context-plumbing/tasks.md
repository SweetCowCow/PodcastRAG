## 1. Backend dependency 實作

- [x] 1.1 在 `backend/app/api/deps.py` 新增 `bind_eval_context` FastAPI dependency（決策來自 Decision 3：Bind 點用 FastAPI dependency 不用 middleware）：函式簽名 `async def bind_eval_context(request: Request, user: User = Depends(get_current_user))`，內部讀 `X-Eval-Run-Id` / `X-Eval-Item-Id` / `X-Eval-Turn-Idx`，當三 header 齊全且 `user.role == "admin"` 且 `turn_idx` 可 parse 為 `int(>=0)` 時呼叫 `set_eval_context()`、yield、然後 finally `reset_eval_context()`；否則直接 yield 不動 ContextVar。**驗證**：以 manual python REPL 匯入 deps 模組、實例化 `Request` mock + admin/non-admin user 各跑一次、assert `get_eval_context()` 在 yield 期間值正確、yield 後回 None
- [x] 1.2 在 `/shows/{show_id}/query` endpoint signature 加 `_eval_ctx: None = Depends(bind_eval_context)` 參數（決策來自 Decision 2：Auth gate 共用 `?debug_trace=true` admin gate），確保 chat agent handler 執行期間 ContextVar 已 bind 完。此步同時把 Implementation Contract 段裡的「行為（observable）」契約落地——admin + 三 header 齊全 → 該 request lifetime ContextVar 為 dict、結束回 None。**驗證**：`curl` 以 admin session + 三 header 打 `/query?debug_trace=true`、後端 log 應出現 set_eval_context 觸發訊息（手動 add logger.info 確認後可移除）
- [x] 1.3 新增 `backend/tests/test_eval_context_dependency.py`：至少四 case（admin + 三 header 齊 → set；non-admin + 三 header 齊 → 不 set；admin + 缺 header → 不 set；admin + malformed turn_idx → 不 set），交付的行為是 `bind_eval_context` 對應 Backend SHALL bind eval context from admin-issued HTTP headers on the chat query endpoint requirement 的四個 Scenario，並覆蓋 Implementation Contract「Failure modes」（header 缺 / malformed 靜默 skip 不 4xx）與「Acceptance criteria」第一條（至少三 case 通過）。**驗證**：`pytest backend/tests/test_eval_context_dependency.py -v` 全綠

## 2. Runner v2 注入 + run_id 生成

- [x] 2.1 在 `backend/scripts/run_chat_agent_eval_v2.py` startup 段生成 `run_id`，格式 `eval-YYYYMMDDTHHMMSSZ-<8-char-hex>`（決策來自 Decision 4：run_id 命名 = ISO 時間 + 8 字隨機）；加 `--run-id <str>` CLI flag 覆寫 default。**驗證**：跑 `python -m backend.scripts.run_chat_agent_eval_v2 --help` 應顯示 `--run-id` 選項；無 flag 跑一次空 run（or dry-run mode）log 應印出符合 regex `eval-\d{8}T\d{6}Z-[0-9a-f]{8}` 的 run_id
- [x] 2.2 在 runner 每 turn HTTP POST 前加 3 個 header `X-Eval-Run-Id` / `X-Eval-Item-Id` / `X-Eval-Turn-Idx`（決策來自 Decision 1：Transport 用 HTTP header 不用 query string 或 body），交付的行為是 Chat agent eval runner SHALL generate a run_id and propagate it as an HTTP header 的兩個 Scenario，同時固定 Implementation Contract「介面 / data shape」中三個 header key 與 value 型別。**驗證**：對 backend 跑 calibration_8 一輪、後端用 `request.headers.get("X-Eval-Run-Id")` log 抽樣三筆、確認 multi-turn item 的 turn_idx 隨輪數遞增
- [x] 2.3 在 runner 結果 JSON 頂層 metadata 加 `run_id` 欄位（在現有 `backend_commit` / `timestamps` 旁邊）。**驗證**：`jq '.run_id' <result.json>` 印出非空字串、值與 runner stdout 印的 run_id 一致

## 3. SQL RCA demo script

- [x] 3.1 新增 `backend/eval/scripts/sql_rca_demo.py`（決策來自 Decision 5：SQL RCA demo script 跟 plumbing 一起 ship），交付的行為是 Eval runner SQL RCA demo script SHALL exist and produce three-section output 的 Scenario：CLI 接受 `--run-id` 必填、`--compare-run-id` 選填，輸出三段 SQL 結果（per-turn span count / 跨 run search_query diff / per-turn tool timeline）。**驗證**：對 step 2.2 跑出來的 run_id 執行 `python -m backend.eval.scripts.sql_rca_demo --run-id <r>`、三段輸出皆非空、第一段 distinct item_id ≥ 8（對應 calibration_8）

## 4. prompt_fingerprint_diff SQL 路徑

- [x] 4.1 在 `backend/eval/scripts/prompt_fingerprint_diff.py` 加 `--source` flag（預設 `http`、新增 `sql`）+ `--run-id-old` / `--run-id-new` 參數；當 `--source=sql` 時 bypass `_run_eval_for_backend`、改從 `eval_traces` SELECT `search_query` per (item_id, turn_idx, tool_name)，交付的行為是 Prompt fingerprint diff SHALL support SQL-backed comparison 的 Scenario。**驗證**：對兩個不同 run_id 跑 `--source=sql`、輸出 markdown table 結構與既有 HTTP-inline 版本一致（item / turn / tool / old / new / changed 六欄）

## 5. End-to-end verify + Tier 1 ready

- [x] 5.1 對 prod backend 跑一輪完整 `_calibration_8.json` v2 runner、抓 `run_id`、跑 SQL `SELECT COUNT(*), COUNT(DISTINCT item_id) FROM eval_traces WHERE run_id = '<r>'`，交付的行為是 PG eval_traces SHALL contain populated run_id, item_id, and turn_idx for runner-driven requests 的 Scenario（runner-driven turn writes spans with populated locator columns）。**驗證**：COUNT(*) > 0 且 distinct item_id ≥ 8；隨機抽 3 列 `SELECT run_id, item_id, turn_idx, span_type FROM eval_traces WHERE run_id = '<r>' LIMIT 3` 三欄全 NOT NULL
- [x] 5.2 補一筆 prod user 流量 negative verify（前端登入非 admin 帳號發一次 chat query 或用 curl 模擬無 X-Eval header），交付的行為是 prod user traffic with no eval context does NOT write to eval_traces 的 Scenario。**驗證**：query 前後 `SELECT COUNT(*) FROM eval_traces` 數字一致
- [x] 5.3 將本 change 在 `docs/case-studies/` 留下 verify 紀錄（含 run_id、SQL 截圖或文字輸出、Tier 1 b20 RCA flow 範例 SQL），同時對照 Implementation Contract「Scope boundaries」清單核對 in-scope 項目皆已交付、out-of-scope 項目皆未被觸碰。**驗證**：case study 檔案存在、內含至少一段 SQL output 證實 plumbing 通了；Tier 1 follow-up `chunk-level-retrieval-rca-b20-style` 可直接引用此 SQL flow 起手
