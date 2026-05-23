## Summary

Chat agent 三件補強：(A) 新增 `list_episodes` recency tool + 既有 `find_episodes_by_date_range` 補 `order` / `limit` optional params；(B) verify 既有 multi-turn ordinal carry 在 prod 是否真正生效；(C) SYSTEM_PROMPT 補 explicit「不能編造」清單壓 hallucination severe rate。

## Motivation

`chat-agentic-tool-routing` (2026-05-21 archive) + `enable-agentic-chat-default-on` (2026-05-22 archive) ship 後留 3 個 sharp edge：

- **(A) Recency intent agent 直接放棄**：2026-05-23 prod debug_trace 抓到曼報「最新一集的來賓是誰？」→ `tool_calls=[]` + answer「我目前無法確定最新一集的來賓資訊」(evidence `/tmp/ordinal_evidence/曼報_latest_guest.json` + memory `project_pending_followups.md` item #10)。root cause = 11 個既有 tool 沒任何一個能直接 sort + limit；唯一相關的 `find_episodes_by_date_range` 需 explicit start/end，agent 不會把「最新」翻成 datetime 範圍。同理「最舊 N 集 / 2024 年最後一集歌單 / 上週最舊一集」全部都被丟。
- **(B) Multi-turn ordinal carry 狀態不明**：`chat-agentic-tool-routing` 已實作 `state.last_enumeration_episodes` (FIFO 20) + `_writeback_enumeration_anchor` + `_ORDINAL_INSTRUCTION` 教 agent「第 N 集」對應 `last_enumeration_episodes[N-1]`，但 memory `project_pending_followups.md` item #7（2026-05-20 寫）沒驗證標記，prod 未確認真的 work。
- **(C) Hallucination severe rate 過高**：`enable-agentic-chat-default-on` 翻牌 gate 用放寬版（severe ≤ 20%）通過，spec 初版要求 severe = 0。20% severe rate 在 prod 翻牌觀察期 day 2 仍是 risk，需修。

## Proposed Solution

### (A) Tool surface — 新增 `list_episodes` + 補 `find_episodes_by_date_range` sort/limit

```
list_episodes(
    show_id: UUID,
    *,
    n: int = 5,                                  # max 20
    order: Literal['newest', 'oldest'] = 'newest',
    topic: str | None = None,                    # AND filter, tsquery on episode_description_chunks
    year_start: int | None = None,               # AND filter, inclusive, Taipei calendar year
    year_end: int | None = None,                 # AND filter, inclusive (single year = year_start == year_end)
) -> list[EpisodeRef]
```

SQL 走既有 `episode_finders` 模組新增一個 helper（沿用 `_row_to_episode_ref` 同 shape），用 `EXTRACT(YEAR FROM published_at AT TIME ZONE 'Asia/Taipei')` 做 year filter。

既有 `find_episodes_by_date_range(db, show_id, start, end)` 新增兩個 optional kwarg：

```
find_episodes_by_date_range(
    db, show_id, start, end,
    *,
    order: Literal['newest', 'oldest'] = 'newest',   # NEW
    limit: int | None = None,                         # NEW; None = unbounded (既有行為)
)
```

SYSTEM_PROMPT 加分工 hint：
- 「需要 sort 或限定數量」→ `list_episodes` / `find_episodes_by_date_range` 帶 `limit`
- 「列出全部符合」→ 既有 `find_episodes_by_topic` / `_by_guest`（無 limit）
- 「相對日期（上週 / 上個月 / 最近三個月）」→ agent 自算 datetime range 餵 `find_episodes_by_date_range` + limit

### (B) Multi-turn ordinal carry — verify only

不寫新 code。任務只做：

1. Prod chrome-devtools-mcp 跑兩 turn 對話：turn 1「歌單有哪幾集？」turn 2「第三集是什麼內容？」用 `?debug_trace=true` 撈 tool_calls，**驗 turn 2 第一個 tool call 是 `get_episode_summary(episode_id=<last_enumeration_episodes[2]>)` 而非 `find_episode_by_ref(ref='EP3')`**。
2. 加跨節目 scenario（壹加壹電台 / 這又沒有很屌）各跑一次，避開單節目偶然成功。
3. 結果寫進 case study；若 fail，明確標出 root cause 是 prompt wording 還是 state 沒寫回，並 propose 後續 sub-change。

### (C) Hallucination grounding — SYSTEM_PROMPT explicit 不能編造清單

`backend/app/services/chat_agent/prompts.py` 的 SYSTEM_PROMPT 新增「事實 grounding 規則」段落，明列 6 類**絕對不能編造**：

1. 節目名稱（譬如不能把「這又沒有很屌」寫成「也好吃」）
2. 來賓姓名
3. EP 編號
4. 集數標題
5. 來賓具體 quote（引號內的話）
6. 統計數字（X 集 / N 次提到 / 總共 M 分鐘）

未列出（譬如「節目整體傾向」「主題評論」）可從 tool result 合理推論，但**結尾加「請以節目實際內容為準」disclaimer**。不分 two-tier 因為 LLM 對明確列舉的執行率比規則樹高。

## Non-Goals

- **不**動既有 `find_episodes_by_topic` / `find_episodes_by_guest` / `find_episode_by_ref` 三 finder 的 signature（本 change 只加 sort/limit 到 `find_episodes_by_date_range`，topic/guest finder 如果未來需要再單獨開 change）。
- **不**改 `list_episodes` 走 `topic` filter 的下游 SQL（沿用 `find_episodes_by_topic` 同套 tsquery on `episode_description_chunks` 邏輯，不重寫 retrieval）。
- **不**改 multi-turn ordinal carry 既有 code path — 本 change 是 verify-only，若 prod 重驗 fail 才另開 sub-change。
- **不**動 `state.last_enumeration_episodes` 的 FIFO cap (20) 或 TTL（這是 `chat-agentic-tool-routing` 既有設計，不重新討論）。
- **不**為 hallucination 加 RAG-only mode（譬如「所有事實 claim 必須來自 tool result citation」）— 太激進，先用 explicit 清單做第一輪壓制。
- **不**改 LLM judge metric（既有 `extended-multi-turn-40` + judge prompt 不變，本 change 用相同 metric 跑前後比對）。
- **不**改 11 → 12 個 tool 之外的 agent loop / 並行 / token budget / circuit breaker 任何邏輯。

## Alternatives Considered

- **General `list_episodes(sort_by, order, limit, ...filter)` kitchen sink**：拒。LLM 對 enum `sort_by` 不穩（會發明 `popularity` 等不存在的值），且目前只有 `published_at` 一個合理排序維度。
- **不開新 tool，只加 `order` + `limit` 到 4 個既有 finder**：拒。`find_episodes_by_topic` 加 limit 後 query「歌單最新 3 集」是 work 但「show 全集最新 3 集」（無 topic filter）沒入口可用。
- **multi-turn ordinal carry 直接改 prompt wording 而不先 verify**：拒。可能浪費 implementation effort 在不存在的 bug 上；prod evidence 優先。
- **hallucination 用 two-tier 規則樹（絕對不能 vs 可以推論）**：拒，per discuss 收斂 — LLM 對明確 enumeration 執行率比 nested branching 高。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `chat-agentic-routing`: 11 callable tool surface 擴成 12 個（新增 `list_episodes`）；既有 `find_episodes_by_date_range` tool 新增 `order` + `limit` optional kwarg；SYSTEM_PROMPT 新增「事實 grounding 規則」段落明列 6 類不能編造項目；ordinal carry 驗證在 prod 真正生效。

## Impact

- Affected specs: chat-agentic-routing
- Affected code:
  - Modified:
    - backend/app/services/episode_finders.py
    - backend/app/services/chat_agent/tools.py
    - backend/app/services/chat_agent/prompts.py
  - New:
    - backend/tests/test_list_episodes_recency.py
    - backend/tests/test_chat_agent_grounding_prompt.py
  - Removed:
    - (none)
