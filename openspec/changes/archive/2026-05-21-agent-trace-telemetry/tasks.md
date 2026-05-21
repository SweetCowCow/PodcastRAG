## 1. Schema 與 trace dataclass

> 對應 requirement: **Agent loop emits per-stage telemetry trace**
> 對應 design: **Decision 1: telemetry 欄位放 ChatAgentResult，不放獨立 store**、**Decision 5: tool result 完整保留只在 admin trace，不進 default response**


- [x] 1.1 在 `backend/app/services/chat_agent/agent.py` 新增 `LLMCallTrace` 跟 `StageTimings` dataclass，**實作 spec 「Agent loop emits per-stage telemetry trace」**（含 docstring 注明 prompt_tokens 是該 round total 含 history）
- [x] 1.2 `ChatAgentResult` dataclass append `llm_calls: list[LLMCallTrace]` 跟 `stage_timings: StageTimings` 欄位（default factory）
- [x] 1.3 `backend/app/schemas/query.py` 的 `ToolCallTrace` Pydantic model append `result_full: str | None = None` 欄位
- [x] 1.4 `backend/app/schemas/query.py` 新增 `LLMCallTraceResponse` `StageTimingsResponse` `AgentTraceResponse` Pydantic models（response 用）
- [x] 1.5 `QueryResponse` 或 chat response 既有 model append `trace: AgentTraceResponse | None = None`

## 2. agent.py instrument

> 對應 requirement: **Agent loop emits per-stage telemetry trace**
> 對應 design: **Decision 2: per-stage timing 用 context manager + perf_counter**


- [x] 2.1 `run_agent` 開頭新增 `stage_t0 = time.perf_counter()` 跟 5 個 stage 的 elapsed 變數
- [x] 2.2 包 `state_store.load` 計 `state_load_ms`
- [x] 2.3 包 `build_messages` 計 `build_messages_ms`
- [x] 2.4 LLM loop 內每輪 `client.chat.completions.create` 前後 perf_counter 取 `latency_ms`、塞 `LLMCallTrace` 進 list（含 finish_reason、token usage）
- [x] 2.5 包 `state_store.save` 計 `state_save_ms`（fail-open catch 仍要在）
- [x] 2.6 包 `_try_update_summary` 計 `history_summary_ms`
- [x] 2.7 build `StageTimings` 物件、塞進 `ChatAgentResult`

## 3. Admin debug gate

> 對應 requirement: **Query endpoint exposes trace under admin debug gate**
> 對應 design: **Decision 3: admin-only gate 用 query param + role check**


- [x] 3.1 `backend/app/api/query.py::query_show` 簽名加 `debug_trace: bool = Query(default=False)`，**實作 spec「Query endpoint exposes trace under admin debug gate」**
- [x] 3.2 `query_show` 取得 `current_user`（既有 dependency）後加判斷 `include_trace = debug_trace and current_user.is_admin`
- [x] 3.3 agent path 的 `_agent_result_to_response` 接受 `include_trace` 參數：True 時把 `agent_result.llm_calls` / `stage_timings` / `tool_calls` 含 `result_full` 都塞進 response；False 時 trace 欄位 = None、result_full = None
- [x] 3.4 rule-based path（非 agent）下 `trace` 欄位也回 None（不 instrument rule-based pipeline）

## 4. Tool result_full populate

> 對應 requirement: **Query endpoint exposes trace under admin debug gate**
> 對應 design: **Decision 5: tool result 完整保留只在 admin trace，不進 default response**


- [x] 4.1 `agent.py` 收 tool dispatch 結果時，永遠把完整 `result_str` 暫存在 trace entry 的 `result_full` slot（即使 admin gate 關，先存好）
- [x] 4.2 API layer 決定 serialize 時看 `include_trace`：False 把 result_full 刷成 None 才回給 user

## 5. Unit tests

- [x] 5.1 新增 `backend/tests/test_chat_agent_telemetry.py`，覆蓋三個 scenario：成功 turn / truncate turn / state_save fail-open；驗證 `ChatAgentResult` 結構含 trace
- [x] 5.2 新增 `backend/tests/test_query_debug_trace_gate.py`，覆蓋 admin+debug=true / 非 admin+debug=true / admin+no debug 三組 case
- [x] 5.3 跑 `pytest backend/tests/test_chat_agent_*.py` 確認既有測試沒 regression

## 6. Local script

> 對應 requirement: **dogfood_trace_dump script captures 30-question trace for offline analysis**
> 對應 design: **Decision 4: trace dump script 走 prod API 不走 zeabur exec**


- [x] 6.1 `backend/scripts/dogfood_trace_dump.py` 寫主流程，**實作 spec「dogfood_trace_dump script captures 30-question trace for offline analysis」**：load session_id + csrf_token 從 playwright-state.json、loop 30 題、retry 1 次、落本機 JSON
- [x] 6.2 script 對 5xx / timeout 失敗紀錄 `{"id":..., "error":...}` 而非 trace、繼續下一題
- [x] 6.3 script 完成後 print summary：n_success / n_error / total_latency

## 7. Prod 驗證 + trace 蒐集

- [x] 7.1 git commit + push → Zeabur build 觸發
- [x] 7.2 確認 backend redeploy 完成、RUNNING 狀態（per `feedback_zeabur_env_update_no_restart.md` 順序紀律）
- [x] 7.3 用 admin session 打 prod 1 題 with `?debug_trace=true` 驗證 trace 出現，schema 對齊
- [x] 7.4 跑 `python3 backend/scripts/dogfood_trace_dump.py` 落 30 題 trace JSON
- [x] 7.5 確認 `.tmp/dogfood_trace_2026-05-22.json` 30 entries 完整、stage_timings 都有值

## 8. Trace 分析 + case study append

- [x] 8.1 寫分析 script（一次性 `.tmp/analyze_trace.py` 不入 git）：算 30 題 stage latency 的 mean / p50 / p95 / max
- [x] 8.2 對 q01 / q02 / q03 / q05 四題 deep dive：列每題的 tool_calls sequence + result_full snippet + LLM round per-round finish_reason + 失敗訊號出現位置
- [x] 8.3 把 deep dive 結果分類成「tool ValidationError 翻譯」「prompt 沒指引 noise→hallucination」「其他」三類，數出比例
- [x] 8.4 在 `docs/case-studies/rag-vs-long-context-2026-05-22.md` append 新 section「Agent loop trace 分析」含：4 題 deep dive 並排、30 題 stage latency 表、root cause 分類比例、waterfall ASCII 圖
- [x] 8.5 確認 case study 仍保持 `feedback_case_studies_no_commit.md` 規則（不入 git）

## 9. Archive 前驗證

- [x] 9.1 跑 `spectra verify agent-trace-telemetry` 確認所有 task 完成
- [x] 9.2 確認 prod 仍正常運作（chat query 200 + 非 admin 不會看到 trace）
- [x] 9.3 確認沒新的 prod error（zeabur log 抓不到時用 `?debug_trace=false` 跑一題確認 graceful）
- [ ] 9.4 跑 `spectra archive agent-trace-telemetry` 進 archive
