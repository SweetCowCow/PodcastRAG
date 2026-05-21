## Context

`chat-agentic-tool-routing`（archive 2026-05-21）把 chat 系統升級為 agent loop，11 個 tool 透過 `_dispatch_tool` 統一派發。`agent-trace-telemetry`（archive 2026-05-21 晚）加上完整 trace 工具，跑 30 題 dogfood 抓到 q03 失敗 case，呈現三層 bug：SQL typo（`_get_episode_segments`）→ PG transaction 進 aborted state → 後續 tool 全被連坐 → LLM 把 raw exception 翻譯給 user。

Phase 2 要翻 `ENABLE_AGENTIC_CHAT=true` default 之前，這個 root cause 必須清掉，否則使用者真實體驗到「系統查詢時遇到了技術問題」會炸鍋。

本 change 不是「修一個 typo」這麼單純——q03 是個契機，順手把 tool dispatch 的錯誤處理機制升級成可長期撐住的結構（SAVEPOINT 隔離 + structured envelope），讓未來新 tool 不用再個別處理 exception 邊界。

## Goals / Non-Goals

**Goals：**

- 修 `_EPISODE_SEGMENTS_SQL` 的 column 名錯誤，跟 `transcript_segments` model 對齊
- `_dispatch_tool` 內每個 tool callable 用 SAVEPOINT 包起來，exception 時 SAVEPOINT 自動 rollback，不污染外層 session
- 把 raw exception 在 dispatch 層轉成結構化 Tool error envelope：`{ok, kind, internal_message, user_hint}`，給 LLM `kind` 做決策、給 user `user_hint`、留 `internal_message` 給 trace / log
- System prompt 加規則：tool result `ok=false` 時用 `user_hint`，不暴露 internal message

**Non-Goals：**

- 不做自動 retry policy（YAGNI——尚未實證哪類錯該 retry）
- 不加告警 / 閾值（YAGNI——traffic 還不夠）
- 不寫 admin dashboard 看 per-tool error 分佈（先靠 trace 觀察）
- 不重寫 tool dispatch 整體流程（在現有 `_dispatch_tool` 加 SAVEPOINT + envelope wrap，11 個 tool 簽名 / return shape 不動）
- 不引 integration test 跑真 PG（unit test 全 mock，SQL 對 column 用 string assertion）
- 不 audit 其他 10 個 tool 的 SQL（沒見過拋過 exception，YAGNI）

## Decisions

### Decision 1：SAVEPOINT 隔離 vs `db.rollback()` vs 獨立 connection

採用：`async with ctx.db.begin_nested():` 包每個 tool callable（SQLAlchemy AsyncSession 的 nested transaction = PG SAVEPOINT）。

替代方案：
- (a) `db.rollback()` after catch exception：簡單，但會把整 session 的所有 pending state（包括 chat_session L1 state 寫入）一併丟掉
- (b) 每個 tool 走獨立 `AsyncSession`：最強隔離，但要改 ToolContext + 多開連線池消耗 + 跨 tool 共享 ctx.state 變複雜

選擇理由：SAVEPOINT 是 PG 原生機制，cost 低（per-tool nested begin 約 < 1ms）+ 不會誤殺 outer session 其他 pending writes。失敗只 rollback 該 tool 自身的 SQL 變動，下一個 tool 拿到的是 outer-savepoint 之前的乾淨狀態。這正是「per-tool isolation」最小化的正確抽象層。

### Decision 2：Tool error envelope 結構

採用：
```python
{
    "ok": False,
    "kind": "validation" | "schema" | "transient" | "not_found" | "unknown",
    "internal_message": "<ExceptionClass>: <msg>",
    "user_hint": "<friendly message in zh-TW>",
}
```

替代方案：
- (a) 只加 `kind`，保留現有 `error` key：相容舊行為但 LLM 不知道要看 `kind` 還是 `error`，schema 不純
- (b) 把 envelope 也應用到成功 case（`{"ok": true, "data": ...}`）：純化更徹底，但要動 11 個 tool 的 return + 改 prompt + 改 trace 顯示，遠超本 change scope

選擇理由：(a) 半套不純，未來再升級成本更高；(b) 滿足純化但 YAGNI——成功 case 沒有 root cause 痛點，現在不該動。本 change 只在 failure path 引入結構化，成功 path 維持 raw dict。

### Decision 3：`_classify_exception` dispatch table 範圍

採用最小化 5 個 kind：

| Exception | kind |
|---|---|
| `pydantic.ValidationError` | validation |
| `sqlalchemy.exc.ProgrammingError`, `IntegrityError`, `DataError` | schema |
| `asyncio.TimeoutError`, `asyncpg.PostgresConnectionError`, `OperationalError` | transient |
| `LookupError` / 自家 `NotFoundError`（若有）| not_found |
| 其他 | unknown |

替代方案：枚舉 20+ 種 exception 類別、依 prod log 統計訂閾值。

選擇理由：5 個 kind 涵蓋 dogfood 看到的所有實證 case（q03 ProgrammingError + ValidationError 在 ToolCallTrace 出現過）。其他 kind 屬 YAGNI——prod traffic 累積實證再擴。

### Decision 4：System prompt 規則寫在哪、寫多細

採用：`backend/app/services/chat_agent/memory.py::build_messages` 拼 system prompt 時 append 一個常數段落（沿用既有 SYSTEM_PROMPT 結構），內容含一條 rule + 一個 example：

```
Tool 錯誤處理規則：
若 tool result 含 `ok: false`，回給使用者時必須用 `user_hint` 欄位的文字基底改寫，
**禁止**輸出 `internal_message` 或 exception class name（譬如 ProgrammingError）。

範例：
tool 回傳 {"ok": false, "kind": "schema", "user_hint": "這次查詢沒撈到完整資料"}
→ 給 user：「我這次沒能完整查到相關內容，能不能換個方式問或補充更多線索？」
```

替代方案：在 dispatch 層直接把 envelope 簡化成只回 `user_hint`，LLM 看不到 internal kind / message。

選擇理由：給 LLM 看 `kind` 有實際決策價值（譬如 `transient` LLM 可能換 tool 試、`schema` LLM 知道這 tool 壞了不要再呼），prompt-only 規範比 dispatch 層魔術更透明。

### Decision 5：q03 verification 走 prod 真實 query 不靠 unit test

採用：archive 前一定要對 prod 跑「迪拉胖 EP134 開工歌單觀念」這題（admin session + `?debug_trace=true`），驗 `_get_episode_segments` `raised=None` + 答案不含「技術問題」訊號。

替代方案：只跑 unit test，prod 驗證等下次 dogfood 自然遇到。

選擇理由：本 change 緊耦合到 prod schema（real PG column 名），mock unit test 跑得過不代表 prod 跑得過。q03 是已知 reproducer，archive 前花 30 秒打一發 prod 驗就確認。

## Implementation Contract

**Behavior:**

- `get_episode_segments(EP134, topic_filter="歌單")` 對 prod PG 成功回 segments list（含 `start_sec` / `end_sec` 純數字，不再拋 ProgrammingError）
- 同 agent loop 內如果某 tool 拋 exception，後續 tool 的 SQL 仍能正常執行（不出現 `InFailedSQLTransactionError`）
- 任何 tool 失敗時，回 LLM 的 dict 結構是 envelope `{"ok": false, "kind": "...", "internal_message": "...", "user_hint": "..."}`，**不再**是 `{"error": "..."}`
- 任何 tool 失敗時，LLM 給 user 的最終 answer 文字基於 `user_hint`，**不含** `ProgrammingError` 等 exception class name、`internal_message` 內容、或 "技術問題 / 系統查詢 / 資料存取" 字眼

**Interface / data shape:**

```python
# tools.py 新增
def _classify_exception(exc: Exception) -> tuple[str, str]:
    """回 (kind, user_hint)。"""
    ...

# _dispatch_tool exception handler 改回：
return (
    {
        "ok": False,
        "kind": kind,
        "internal_message": f"{type(exc).__name__}: {exc}",
        "user_hint": hint,
    },
    type(exc).__name__,
    elapsed,
)

# 每個 tool callable 改包：
async with ctx.db.begin_nested():
    result = spec.callable(validated, ctx)
    if inspect.isawaitable(result):
        result = await result
```

`ChatAgentResult` / `ToolCallTrace` schema **不變**（既有 `raised`、`result_summary`、`result_full` 欄位繼續對 envelope dict 序列化）。

System prompt 在 `memory.py` 既有 SYSTEM_PROMPT 後 append 新區塊「Tool 錯誤處理規則」+ 一個範例。

**Failure modes:**

- `begin_nested()` 本身失敗（譬如 outer transaction 已掛）：catch + log warning，回 envelope `kind="transient"`，不阻塞 agent loop
- `_classify_exception` 遇未認知 exception：fallback `kind="unknown"` + 通用 `user_hint`「這次查詢遇到一點狀況」
- Prompt 規則 LLM 沒遵守（偶爾仍翻譯 internal_message）：unit test 不抓，prod 觀察。若高頻發生再 propose 改強規範或 dispatch 層直接刷掉 internal_message
- prod 驗證 q03 仍失敗：rollback commit + 開新 debug session 看 trace

**Acceptance criteria:**

- `python3 backend/scripts/dogfood_trace_dump.py` 跑完 30 題，q03 的 `_get_episode_segments` trace entry `raised=None`，answer 文字不含「技術問題 / 系統查詢」
- `pytest backend/tests/test_chat_tool_error_isolation.py` 全綠（≥ 5 test：SQL column / SAVEPOINT 隔離 / 4 個 kind）
- `pytest backend/tests/test_chat_agent_*.py` 既有 18+ 測試零 regression
- prod admin session 對「迪拉胖 EP134 開工歌單」query 帶 `?debug_trace=true`，response.trace.tool_calls 內 `_get_episode_segments` 成功；answer 文字看不到 internal 失敗訊號

**Scope boundaries:**

- In scope：`tools.py`（SQL fix + dispatch SAVEPOINT + classifier + envelope return shape）/ `memory.py`（system prompt 新規則）/ 新測試檔
- Out of scope：retry policy / 告警 / dashboard / 其他 tool SQL audit / 成功 path envelope 化 / integration test infra

## Risks / Trade-offs

- **[Risk] SAVEPOINT 多一層 begin/commit overhead** → Mitigation：實測 PG nested begin < 1ms，相比 LLM round 平均 1-7s 完全可忽略
- **[Risk] LLM 偶爾仍翻譯 internal_message**（prompt only，沒有硬規則）→ Mitigation：先 prompt only + prod 觀察；若觀察到頻繁違反再升級到 dispatch 層直接 strip
- **[Risk] `_classify_exception` 漏分類某 exception** → Mitigation：fallback `kind="unknown"` 不會炸；prod trace 觀察 unknown 比例若高則擴 dispatch table
- **[Risk] outer transaction 在 begin_nested() 時剛好掛掉**（罕見）→ Mitigation：catch BaseException、log warning、回 envelope transient，agent loop 該 turn 仍能完整跑完

## Migration Plan

1. 本機 docker compose 起 prod-like 環境，跑既有 `pytest backend/tests/test_chat_agent_*.py` 過
2. 寫 + 跑新測試 `test_chat_tool_error_isolation.py` 全綠
3. 本機 chat UI 手動測一題「迪拉胖 EP134 開工歌單」（mode=chat + `ENABLE_AGENTIC_CHAT=true`），確認 prod-like 環境拿到正常答案
4. git commit + push → Zeabur build → backend RUNNING
5. Admin session 對 prod 重打同一題 with `?debug_trace=true`，驗 trace + answer
6. 跑一次完整 30 題 dogfood，存 `.tmp/dogfood_trace_2026-05-22-postfix.json`（不入 git），對比 prefix 版本確認 q03 改善
7. Case study 補一段 before/after：q03 trace 對比 + envelope 結構示意
8. Rollback：commit revert + redeploy 即還原；envelope 改動屬非破壞（既有 tool 簽名 / `ChatAgentResult` schema 不變）

## Open Questions

- Prompt 規則用「Tool 錯誤處理規則」標題 + 一個範例夠不夠強？實測 LLM 偶有違反才知道。先 ship、觀察、迭代
- Phase 2 default=true 翻牌前要不要再跑一次完整 30 題＋multi-turn 4 dialogs（用 `extended-multi-turn-40.json`）夯實？傾向要——但屬下一個 change `chat-multi-turn-trace-investigation`
