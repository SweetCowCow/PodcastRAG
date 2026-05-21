## Context

PodcastRAG chat 系統在 2026-05-19 透過 `chat-agentic-tool-routing` archive 升級為 agent loop（OpenAI native tool calling + 11 callable + Pydantic strict schema），預設 flag `ENABLE_AGENTIC_CHAT=false`，靠 admin email allowlist gate 翻 true 進 Phase 1 dogfood。

2026-05-21 的 4-arm RAG vs Long Context benchmark（30 題 golden set）發現 D agentic arm 雖然 LLM-as-judge OVERALL 0.765 領先其他 arm，但**質化失敗模式明顯**：

- q01 節目名稱由來、q03 EP134 開工歌、q05 UK Drill 等題答出「技術問題阻止檢索」「資料存取似乎遇到問題」這類面向使用者的失敗訊息
- q02 嘻哈冠軍陷阱題從 noise tool result 編造「節目中提及歌唱比賽相關話題」

兩種失敗 root cause 可能不同（tool exception 翻譯 vs noise→hallucination），但目前 `ChatAgentResult.tool_calls` trace 僅含 per-tool latency 與截斷 500 字的 result_summary，**無法明確分類**也無法繪製 per-stage waterfall。

修復翻 default 前必須先「看清楚」問題，本 change 就是把放大鏡架好，不修問題本身。

## Goals / Non-Goals

**Goals:**

- agent loop 跑完一輪 chat turn 後，回傳結構完整含：(1) 每個 LLM round 的 latency / token / finish_reason；(2) 每個 stage（build_messages / state_load / state_save / history_summary）的 elapsed_ms；(3) 完整 tool result（不截斷）
- `/query` endpoint 帶 telemetry 必須有 admin-only gate，不能讓普通 user 透過 query param 撈到 prod tool 內部結果
- 提供 local script 跑 30 題重打 prod、落本機 JSON 給離線分析
- Trace 蒐集完做 root cause 分類 + waterfall 圖落入 case study

**Non-Goals:**

- 不修 root cause（prompt 改寫 / ref→uuid sequence enforcement / noise→hallucination 強化）
- 不重跑 4-arm benchmark
- 不對 telemetry endpoint 做 rate limit / per-session quota / 對外開放
- 不改 ToolCallTrace 既有欄位 schema（保留 result_summary 兼容前端展示），只 append result_full
- 不 instrument Redis / DB layer 內部 timing

## Decisions

### Decision 1: telemetry 欄位放 ChatAgentResult，不放獨立 store

採用：把 `llm_calls` 和 `stage_timings` 直接掛在 `ChatAgentResult`，跟 `tool_calls` 同層次。

替代方案：新建 `AgentTraceStore`（Redis 或 DB），non-blocking 寫進去，trace 從那邊撈。

選擇理由：每 turn 的 trace 跟該 turn response 同生命週期，沒人會跨 turn 查 trace；獨立 store 引入序列化 + race condition + GC 額外複雜度，不值得。trace 跟 response 一起回，consumer（local script）一次拿到。

### Decision 2: per-stage timing 用 context manager + perf_counter

採用：在 `agent.py` 用 `time.perf_counter()` 開頭結尾取差，累積進 `StageTimings` dataclass。

替代方案：(a) 用 opentelemetry SDK；(b) 用 contextvars + middleware。

選擇理由：方案 (a) 引入 OTLP collector + exporter 配置，跟「離線本機分析」目的不符；方案 (b) 對 5 個 stage 過度抽象。簡單 perf_counter pair 已足夠，code 增量 ~30 行可讀。

### Decision 3: admin-only gate 用 query param + role check

採用：`/shows/{show_id}/query?debug_trace=true` + 該 session 必須是 admin role（看 `current_user.is_admin`）才回 telemetry。普通 user 帶這 query param 也只拿到 response 不含 telemetry 欄位。

替代方案：(a) 獨立 endpoint `/admin/chat/query-with-trace`；(b) 看 env flag 全域啟用 (`AGENT_TRACE_PUBLIC=true`)。

選擇理由：方案 (a) 跟 prod query path 不對稱、testing 路徑分裂、要重寫 quota / CSRF / origin check；方案 (b) 失去使用者粒度，dogfood 不在意但「下個 admin 介面 debug 工具」需要這層 gate。query param + role 是最小入侵。

### Decision 4: trace dump script 走 prod API 不走 zeabur exec

採用：`dogfood_trace_dump.py` 用 session cookie + CSRF 重打 prod `/query?debug_trace=true` 30 題，response 含 telemetry 直接落 `.tmp/dogfood_trace_2026-05-22.json`。

替代方案：(a) zeabur service exec 進 backend container 跑 inline；(b) 透過 admin endpoint 直接撈最近 N 個 session 的 trace。

選擇理由：方案 (a) 今天踩過 zeabur exec stdout 投放壞掉的坑（per `feedback_zeabur_env_update_no_restart.md` 同類），不可靠；方案 (b) 需要 server-side trace persistence layer，超出 scope。HTTPS 重打雖然多花 30 quota + 4.5 分鐘 prod traffic，但 reproducible 且不污染 prod state。

### Decision 5: tool result 完整保留只在 admin trace，不進 default response

採用：新增 `result_full: str` 欄位在 `ToolCallTrace`，**只在 admin debug_trace 模式下 populate**；普通 chat response 仍只回 `result_summary`（兼容前端展示）。

替代方案：永遠 populate `result_full`，靠 admin gate 決定回不回。

選擇理由：tool result 含 chunk text（可能上 KB），permanently populate 浪費 memory + serialize cost。lazy 寫入只在 admin path 跑划算。

## Implementation Contract

**Behavior:**

- 任何 chat-mode `/query` 請求加上 `debug_trace=true` query param + admin role session：response 多帶 `trace` object，含 `llm_calls`、`stage_timings`、`tool_calls`（其中 `result_full` 已 populate）
- 不加 query param 或非 admin：response 跟現在完全一樣，沒 `trace` 欄位
- agent loop 完成（含 truncate 退出）一律 emit 完整 trace 到 ChatAgentResult，是否回給 caller 由 API layer 決定

**Interface / data shape:**

`ChatAgentResult` 新欄位：

```python
@dataclass
class LLMCallTrace:
    round_index: int          # 0-based
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str         # "stop" | "tool_calls" | "length" | ...
    had_tool_calls: bool

@dataclass
class StageTimings:
    build_messages_ms: float
    state_load_ms: float
    state_save_ms: float
    history_summary_ms: float
    llm_loop_total_ms: float    # 等於 sum(llm_calls) + sum(tool_calls latency)

# ChatAgentResult 已存欄位不動，append:
llm_calls: list[LLMCallTrace]
stage_timings: StageTimings
```

`ToolCallTrace` append `result_full: str | None`（admin trace 模式下塞完整 result JSON，其他模式 None）。

`/query` response schema 加 optional `trace: AgentTraceResponse | None`（pydantic），只在 admin + debug_trace=true 條件下 populate。

**Failure modes:**

- `time.perf_counter()` 失敗：不可能（標準庫），不做 fallback
- LLM call latency 取不到：用 0 填，加 logger.warning，不阻塞 chat
- State load/save failed：既有 fail-open 邏輯不變，stage timing 仍記到 elapsed_ms
- Admin role check 失敗：API 層直接 omit trace 欄位（不報錯，普通 response）
- dogfood_trace_dump.py 對某題 timeout / 5xx：記 error 進 trace JSON、繼續下一題

**Acceptance criteria:**

- `curl -H "Cookie: session_id=<admin>" "/shows/<id>/query?debug_trace=true" -d '{"question":"...","mode":"chat"}'` 回 200 + response.trace 含 llm_calls / stage_timings / tool_calls（result_full populated）
- 非 admin session 同樣請求：response.trace 不存在（response 沒這欄位）
- `python3 backend/scripts/dogfood_trace_dump.py` 跑 30 題完成、落 `.tmp/dogfood_trace_2026-05-22.json`、檔內每題含完整 trace
- case study 加 section「Agent loop trace 分析」含至少 4 題 root cause 分類 + 30 題 stage latency p50/p95 表 + waterfall ASCII / Markdown 圖

**Scope boundaries:**

- In scope: schema 新欄位 / agent.py instrument / API gate / local script / case study append
- Out of scope: root cause 修復（prompt / tool sequence / hallucination 強化下一個 change）/ telemetry persistence / 對外開放 / OTLP exporter

## Risks / Trade-offs

- **[Risk] tool result 全展開可能含敏感資料（譬如 user history summary）** → Mitigation: admin gate 已是基本防護；result_full 只 populate 在 admin path，不會默默寫進 trace store
- **[Risk] 30 次 prod chat 消耗使用者 quota** → Mitigation: 預估 30 次佔 monthly quota 30 / ~unlimited（自己 admin），影響可忽略；blog argument 換 4-arm 完整故事划算
- **[Risk] response payload 變大（含 tool result 完整文字 + 5 段 timing）** → Mitigation: 只在 admin path 展開；普通 user 不受影響
- **[Risk] perf_counter 開頭結尾差 ms 對 short stage（state_load <1ms）誤差大** → Mitigation: 接受誤差，stage timing 目的是「找 latency 大頭」不是精準 profiling
- **[Risk] dogfood_trace_dump.py 重打 prod 過程 prod 系統可能有 transient noise（API rate limit / 偶發 timeout）** → Mitigation: 失敗 retry 1 次，仍失敗就記 error 進 trace 繼續下一題；分析時把 error 題標出來不算進 latency stats

## Migration Plan

1. Schema + agent.py 改完跑 unit test（既有 `test_chat_agent_*.py` 確保沒 regression）
2. Local docker compose 起服務，本機跑 1 題 chat 看 trace 欄位完整
3. Push GitHub → Zeabur build → prod redeploy
4. 用 admin session 打 prod 1 題 with `?debug_trace=true` 驗證 trace 出現、非 admin 不出現
5. 跑 `dogfood_trace_dump.py` 落 30 題 trace JSON
6. 分析 trace + 寫 case study section
7. Rollback：response schema append 屬於 non-breaking（前端不讀新欄位），revert commit + redeploy 即還原

## Open Questions

- 是否要把 trace 額外寫進 logger.info (JSON 格式) 做事後 prod log 撈？目前傾向不 — 已有 debug_trace=true endpoint 即時撈，事後也不需要 reproduce。但若 dogfood 期間發現「user report bad answer 但 trace 沒留」會改變想法
- LLMCallTrace.prompt_tokens 是該 round 累積 prompt 還是 delta？OpenAI API 回的是該 round total（含 history），用 total 就好但要在 schema docstring 注明
