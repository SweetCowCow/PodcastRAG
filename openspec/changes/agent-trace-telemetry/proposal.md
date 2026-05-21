## Why

4-arm benchmark（2026-05-21）發現 D agentic arm 在多題（q01/q02/q03/q05）出現使用者體感「技術問題阻止檢索」「資料存取似乎遇到問題」這類失敗訊息，或從 noise 段落推論編造（q02 嘻哈冠軍陷阱題）。Phase 1 dogfood `ENABLE_AGENTIC_CHAT=true` 已 in production，但翻 default 前必須先**搞清楚問題本質**：是 tool exception 被翻譯成自然語言？還是 prompt 沒指引 LLM 處理 noise tool result？

目前 `ChatAgentResult.tool_calls` trace 已存 per-tool latency，但缺：(1) per-round LLM call latency；(2) per-stage timing（build_messages / state save / history summary 等 background 作業）；(3) tool result 完整內容（目前截 500 字 debug 不夠）。沒有完整 trace 無法明確分類 root cause、也無法畫 waterfall 圖判斷時間花在哪。

**本 change 只做 investigation + telemetry，不做 root cause 修復。**修復策略（譬如 prompt 改寫 / ref→uuid tool sequence 規範 / noise→hallucination prompt 強化）留下一個 change 用本次蒐集到的 trace 做設計依據。

## What Changes

- 擴充 `ChatAgentResult` schema：新增 `llm_calls: list[LLMCallTrace]`（per round 含 latency + token usage + finish_reason）與 `stage_timings: StageTimings`（含 build_messages / state_load / state_save / history_summary 五段 elapsed_ms）
- `ToolCallTrace` 新增 `result_full: str`（完整 tool result，不截斷）保留既有 `result_summary` 截 500 字
- `agent.py` 跑 `run_agent` 時 instrument 各 stage 加 timestamp 標記、收集到回傳的 trace 結構
- `/query` response shape 帶 telemetry 欄位（gate 在 admin-only flag，避免暴露給普通 user — 預設 hidden，帶 `?debug_trace=true` query param + admin session 才回）
- 新增 local script `backend/scripts/dogfood_trace_dump.py`：重打 prod `this-not-that-cool.json` 30 題、落 `.tmp/dogfood_trace_2026-05-22.json`（含完整 trace）
- 分析 trace 落 case study 補充段（rag-vs-long-context-2026-05-22.md 加新 section「Agent loop trace 分析」），含 4 題 deep dive + 30 題 root cause classification + waterfall 圖

## Non-Goals (optional)

- **不修 root cause**：本 change 完成「問題本質確認」後 stop，不改 prompt、不加 tool sequence enforcement、不調 tool description。修復策略下一個 change 開
- **不重 benchmark Arm D**：trace 蒐集完不需要重跑 4-arm。Arm D 既有 result 留作 baseline，修復後新 change 再重跑做 before/after 對比
- **不 instrument 既有 tool dispatch latency**：那層已有 `latency_ms`，本 change 只加 stage 層 timing
- **不 hardening telemetry endpoint 對外暴露**：admin-only gate 已足夠，不做 rate limit / per-session quota

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `chat-agentic-routing`: 新增 telemetry requirement — agent loop 必須 emit per-stage timings + per-round LLM latency + 完整 tool result，回傳到 ChatAgentResult；query endpoint 在 admin-debug 模式下回傳 telemetry 給 caller

## Impact

- Affected specs: `chat-agentic-routing`（modify，加 telemetry requirement）
- Affected code:
  - Modified:
    - `backend/app/services/chat_agent/agent.py`
    - `backend/app/schemas/query.py`
    - `backend/app/api/query.py`
  - New:
    - `backend/scripts/dogfood_trace_dump.py`
    - `docs/case-studies/rag-vs-long-context-2026-05-22.md`（既有，append section「Agent loop trace 分析」）
