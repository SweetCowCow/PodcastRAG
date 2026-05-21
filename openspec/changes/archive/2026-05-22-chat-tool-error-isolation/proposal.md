## Problem

2026-05-21 晚 `agent-trace-telemetry` 跑 30 題 dogfood，q03「EP134 45 歲開工歌觀點」這題使用者拿到的回答是「**系統查詢時遇到了技術問題**」。Trace 顯示三層問題串成同一個失敗：

1. **SQL 寫錯**：`backend/app/services/chat_agent/tools.py::_get_episode_segments` 的 `_EPISODE_SEGMENTS_SQL` 選的 column 名是 `ts.start_seconds` / `ts.end_seconds`，但 `transcript_segments` table 的真實 column 是 `start_time` / `end_time`（per `backend/app/models/transcript_segment.py:21-22`），所以這個 tool 一被呼叫就拋 `ProgrammingError: column ts.start_seconds does not exist`
2. **Transaction 污染擴散**：`_dispatch_tool` catch 了 exception 但沒 rollback PG transaction，整 session 進 aborted state；同一 agent loop 內後續每個 tool（譬如 fallback 用的 `search_within_episode`）都拋 `InFailedSQLTransactionError: current transaction is aborted, commands ignored until end of transaction block`。本來能救場的 tool 全被連坐
3. **LLM 直翻錯誤訊息**：tool result 回 LLM 的格式是 `{"error": "ProgrammingError: column ts.start_seconds does not exist"}`，LLM 直接翻譯給 user「系統查詢時遇到了技術問題，如果你還有其他的問題...」

這是 Phase 2 翻 `ENABLE_AGENTIC_CHAT` default=true 的 blocker——使用者面對「技術問題」訊息會炸鍋。

## Root Cause

每一層獨立看都是常見 bug，但加在一起放大失敗面：

- 第 1 層是純拼字錯誤（commit 8a8cbb1 `chat-agentic-tool-routing` ship 時 SQL 沒有 unit test 對到真實 PG schema，本機 mock 跑得過）
- 第 2 層是 `_dispatch_tool` 寫法問題：catch exception 之後沒做 `db.rollback()` 也沒包 SAVEPOINT，但下一個 tool 共享同一 AsyncSession——PG 的特性是 transaction 進 aborted 後到 ROLLBACK 為止不接任何 query
- 第 3 層是 prompt 沒規範錯誤翻譯邊界，LLM 拿到 `error` key 就照字面寫回 user

## Proposed Solution

四件事一起做（彼此緊耦合）：

1. **修 SQL typo**：`_EPISODE_SEGMENTS_SQL` 內 3 處 `start_seconds` / `end_seconds` 全改回 `start_time` / `end_time`，跟 model 對齊
2. **SAVEPOINT 防護網**：`_dispatch_tool` 內每個 tool callable 用 `async with ctx.db.begin_nested():` 包起來。tool raise 時 SAVEPOINT 自動 rollback，外層 session 保持乾淨，後續 tool 拿到正常 transaction
3. **Tool error envelope**：dispatch 層把 raw exception 轉成結構化 envelope `{"ok": false, "kind": "schema|transient|not_found|validation|unknown", "internal_message": "<class>: <msg>", "user_hint": "<friendly>"}`，新增小型 `_classify_exception` helper 做 dispatch table（`ValidationError → validation` / `ProgrammingError | IntegrityError → schema` / `TimeoutError | asyncpg connection errors → transient` / 其他 → `unknown`）。LLM 從此看 `kind` 決策後續行為，user 視角只看 `user_hint`，`internal_message` 留 trace / log 用
4. **System prompt 規則**：`backend/app/services/chat_agent/memory.py::build_messages` 拼的 system prompt 加一條：tool result 出現 `ok: false` 時，回給 user 用 `user_hint` 措辭，**禁止暴露 `internal_message` / exception class name**

四件事彼此緊耦合：只修 (1) 沒修 (2) 第二個 tool 還是炸；只修 (2) 沒修 (3) LLM 仍會看到 raw exception 翻譯；只修 (3) 沒修 (4) prompt 沒升級看不懂 envelope 結構。

## Non-Goals

- **不在本 change 做的（YAGNI 留 follow-up）**：
  - 自動 retry policy（「transient error 自動 retry N 次」尚未有 prod 實證決定哪類錯該 retry）
  - Per-tool error rate 告警 / 閾值（沒夠多 traffic 訂閾值）
  - Admin dashboard 看每個 tool 的 error 分佈（先讓 trace 蒐證一陣子）
- **不擴 scope 重寫 tool dispatch 機制**：只在現有 `_dispatch_tool` 上加 SAVEPOINT + envelope，11 個既有 tool 簽名 / return shape 不動
- **不引入 integration test 跑真 PG**：所有 unit test 用 mock。SQL 對 column 用 schema-aware string assertion，不跑真 PG migration
- **不改其他既有 tool 的 SQL**：只修 `_get_episode_segments`。其他 tool 在 dogfood 30 題沒見過拋 exception，預先 audit 其他 tool 屬 YAGNI

## Success Criteria

- 在 prod 帶 admin session + `?debug_trace=true` 對 q03「迪拉胖 EP134 開工歌單觀念」query，response.trace.tool_calls 內 `_get_episode_segments` 的 `raised=None`（不再拋 ProgrammingError），且後續 tool 不再有 `InFailedSQLTransactionError`
- 同一個 prod query 的 `answer` 文字不含「技術問題」「系統查詢」「資料存取」等內部失敗訊號
- 模擬 tool 拋 exception 的 unit test：下一個 tool 仍能正常 SELECT（驗 SAVEPOINT 隔離）
- Tool error envelope 結構化 unit test：4 種 `kind`（validation / schema / transient / unknown）各對應正確的 `user_hint`，`internal_message` 含 exception class name 但不混進 `user_hint`
- 既有 `backend/tests/test_chat_agent_*.py` 18+ 既有測試零 regression
- 跑一次 30 題 dogfood `python3 backend/scripts/dogfood_trace_dump.py`，q03 不再出現「技術問題」訊號（before/after 對比寫進 case study）

## Impact

- Affected specs: `chat-agentic-routing`（modify — tool dispatch behavior + system prompt error rule）
- Affected code:
  - Modified:
    - `backend/app/services/chat_agent/tools.py`（修 SQL + `_dispatch_tool` 加 SAVEPOINT + 新增 `_classify_exception` + 改 error return shape）
    - `backend/app/services/chat_agent/memory.py`（system prompt 加 error envelope 規則）
  - New:
    - `backend/tests/test_chat_tool_error_isolation.py`（SAVEPOINT 隔離 + envelope kind/hint 驗證）
