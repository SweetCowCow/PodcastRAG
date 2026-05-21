## 1. SQL typo 修正

> 對應 requirement: **`_get_episode_segments` SQL SHALL reference the real `transcript_segments` columns**
> 對應 design: **Decision 5：q03 verification 走 prod 真實 query 不靠 unit test**

- [x] 1.1 修 `backend/app/services/chat_agent/tools.py::_EPISODE_SEGMENTS_SQL`：3 處 `start_seconds`/`end_seconds` 改成 `start_time`/`end_time`，`ORDER BY ts.start_seconds` 改 `ts.start_time`，**實作 spec「`_get_episode_segments` SQL SHALL reference the real `transcript_segments` columns」**
- [x] 1.2 確認 `_get_episode_segments` 函式內 row mapping（`r["start_sec"]` / `r["end_sec"]`）跟 SELECT 別名一致（不需改但要看）

## 2. SAVEPOINT 防護網

> 對應 requirement: **Agent tool dispatcher SHALL isolate tool errors via SAVEPOINT and return structured error envelope**
> 對應 design: **Decision 1：SAVEPOINT 隔離 vs `db.rollback()` vs 獨立 connection**

- [x] 2.1 `_dispatch_tool` 內 tool callable 執行區塊（既有 `try: result = spec.callable(...) ... except Exception`）改包 `async with ctx.db.begin_nested():`，**實作 spec「Agent tool dispatcher SHALL isolate tool errors via SAVEPOINT and return structured error envelope」的 SAVEPOINT 隔離部分**
- [x] 2.2 處理 `begin_nested` 自身失敗的 fallback：catch + log warning + 回 envelope `kind="transient"` user_hint「這次查詢遇到一點狀況」
- [x] 2.3 確認 `_writeback_enumeration_anchor`（成功 case 的 side effect）仍只在 try 區塊外、tool 成功後執行（不應該被 SAVEPOINT rollback 影響）

## 3. Tool error envelope + classifier

> 對應 requirement: **Agent tool dispatcher SHALL isolate tool errors via SAVEPOINT and return structured error envelope**（envelope 結構 + classifier dispatch table 部分）
> 對應 design: **Decision 2：Tool error envelope 結構**、**Decision 3：`_classify_exception` dispatch table 範圍**

- [x] 3.1 新增 `_classify_exception(exc: Exception) -> tuple[str, str]` helper，依 **Decision 3：`_classify_exception` dispatch table 範圍** 內 5 個 kind 對應表回 `(kind, user_hint_zh_tw)`：validation / schema / transient / not_found / unknown
- [x] 3.2 `_dispatch_tool` exception handler 改回 envelope dict，按 **Decision 2：Tool error envelope 結構** 採 `{"ok": False, "kind": ..., "internal_message": f"{type(exc).__name__}: {exc}", "user_hint": ...}` 取代原 `{"error": "..."}` shape
- [x] 3.3 兩個 catch path（Pydantic `ValidationError` + 一般 `Exception`）都走 `_classify_exception` 統一輸出 envelope
- [x] 3.4 確認既有 `ToolCallTrace.raised`（exception class name）/ `result_summary` / `result_full`（envelope dict 序列化）對新 shape 仍正常

## 4. System prompt 規則

> 對應 requirement: **Agent system prompt SHALL instruct the LLM to use `user_hint` and never expose internal error details**
> 對應 design: **Decision 4：System prompt 規則寫在哪、寫多細**

- [x] 4.1 `backend/app/services/chat_agent/memory.py` 找到既有 SYSTEM_PROMPT 常數，append 新區塊「## Tool 錯誤處理規則」含 1 條 rule（看 ok=false 用 user_hint、禁用 internal_message / exception class name / "技術問題" 等字眼）+ 1 個範例（schema kind tool result → 預期 user 答覆），**實作 spec「Agent system prompt SHALL instruct the LLM to use `user_hint` and never expose internal error details」**
- [x] 4.2 確認 `build_messages` 取 SYSTEM_PROMPT 的路徑包含新區塊（若 SYSTEM_PROMPT 是常數 / module-level 變數則自動帶到）

## 5. Unit tests

> 對應 requirement: **Agent tool dispatcher SHALL isolate tool errors via SAVEPOINT and return structured error envelope**、**Agent system prompt SHALL instruct the LLM to use `user_hint` and never expose internal error details**、**`_get_episode_segments` SQL SHALL reference the real `transcript_segments` columns**

- [x] 5.1 新增 `backend/tests/test_chat_tool_error_isolation.py`，setup 一個 mock ToolContext（mock db with `begin_nested` async context manager）+ mock spec
- [x] 5.2 test_sql_uses_real_columns：對 `_EPISODE_SEGMENTS_SQL` 字串做 assertion，含 `start_time` / `end_time` 不含 `start_seconds` / `end_seconds`，覆蓋 spec scenario「`_get_episode_segments` succeeds on prod schema」的 SQL 前置條件
- [x] 5.3 test_savepoint_isolation：mock 第一個 tool callable 拋 `ProgrammingError`、第二個 tool 拋 normal SELECT；驗 (a) 第一個 tool envelope kind=schema (b) 第二個 tool 仍能跑 (c) outer db.rollback 沒被呼叫，覆蓋 spec scenario「Tool raises ProgrammingError, next tool still works」
- [x] 5.4 test_envelope_validation_kind：mock tool 收到不符 input_model 的 args，驗 `kind="validation"` + `internal_message` 含 "ValidationError" + `user_hint` 不含 ValidationError，覆蓋 spec scenario「Validation error classified」
- [x] 5.5 test_envelope_schema_kind：mock tool 拋 `ProgrammingError`，驗 `kind="schema"` + `internal_message` 含 ProgrammingError + `user_hint` 不含 ProgrammingError / "transaction" / column 名，覆蓋 spec scenario「Schema error classified and user_hint sanitised」
- [x] 5.6 test_envelope_transient_kind：mock tool 拋 `asyncio.TimeoutError`，驗 `kind="transient"` + `user_hint` 是 zh-TW
- [x] 5.7 test_envelope_unknown_kind：mock tool 拋 `RuntimeError`，驗 `kind="unknown"` + `user_hint` 是 zh-TW，覆蓋 spec scenario「Unknown exception falls back gracefully」
- [x] 5.8 test_system_prompt_has_error_rule：load `memory.SYSTEM_PROMPT` 或 build_messages output，驗含「Tool 錯誤處理規則」字串 + 「user_hint」字串 + 「禁止」相關 wording，覆蓋 spec scenario「Tool result with `ok: false` produces user-friendly answer」的 prompt 前置條件
- [x] 5.9 跑 `pytest backend/tests/test_chat_agent_*.py backend/tests/test_chat_tool_error_isolation.py` 確認既有 18+ test 零 regression、新 test 全綠

## 6. Prod 驗證 + ship

> 對應 design: **Decision 5：q03 verification 走 prod 真實 query 不靠 unit test**

- [ ] 6.1 git commit + push → Zeabur build 觸發
- [ ] 6.2 確認 backend redeploy 完成、RUNNING 狀態
- [ ] 6.3 用 admin session 對 prod 打「迪拉胖 EP134 開工歌單觀念」query with `?debug_trace=true`；驗 (a) `_get_episode_segments` trace entry `raised=None` (b) 後續 tool 沒 InFailedSQLTransactionError (c) answer 文字不含「技術問題 / 系統查詢 / 資料存取」訊號，覆蓋 spec scenario「`_get_episode_segments` succeeds on prod schema」+「Tool result with `ok: false` produces user-friendly answer」的 prod path
- [ ] 6.4 對 q03 原 dataset 題（`q03-mid-age-opening-view`）跑一次 `dogfood_trace_dump.py` 全 30 題 → `.tmp/dogfood_trace_2026-05-22-postfix.json`，對比 prefix 版本驗 q03 已修
- [ ] 6.5 確認沒新 prod error（zeabur log 抓 `error|exception` 過去 10 條沒有跟本 change 相關的新 stack trace）

## 7. Case study + archive

- [ ] 7.1 `docs/case-studies/rag-vs-long-context-2026-05-22.md` 在「Agent loop trace 分析」section 後 append 「q03 root cause 修復」小節，含 before/after envelope 結構對比 + prod query before/after answer 對比
- [ ] 7.2 確認 case study 仍不入 git（per `feedback_case_studies_no_commit.md`）
- [ ] 7.3 `spectra validate chat-tool-error-isolation` 過、所有 task 標完成
- [ ] 7.4 `spectra archive chat-tool-error-isolation` 進 archive
