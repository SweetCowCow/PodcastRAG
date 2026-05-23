## Context

`chat-agentic-tool-routing` (2026-05-21 archive) ship 了 agent loop + 11 個 callable tool；`enable-agentic-chat-default-on` (2026-05-22 archive) 翻 `ENABLE_AGENTIC_CHAT` default=True 並設 14 天觀察期。觀察期 day 2 (2026-05-23) 跑 admin-quota-bypass-fix 重跑 token-truncate eval 時順手抓到兩件 prod-confirmed sharp edge + 一件 archive 期間就知道但放寬 gate 過了的 hallucination 問題。

### 既有結構快照（2026-05-23）

| 模組 | 角色 |
|---|---|
| `backend/app/services/chat_agent/agent.py` | Agent loop（OpenAI native tool calling, multi-round, tool budget, token budget guard） |
| `backend/app/services/chat_agent/tools.py` | 11 個 callable tool: `find_episode_by_ref` / `find_episodes_by_guest` / `find_episodes_by_topic` / `find_episodes_by_date` / `get_episode_summary` / `get_episode_segments` / `search_within_episode` / `search_across_episodes` / `search_in_episodes` / `get_show_overview` / `pin_episode` + `unpin_episode` |
| `backend/app/services/chat_agent/prompts.py` | SYSTEM_PROMPT，含 tool routing guidance + tool error handling 規則 |
| `backend/app/services/chat_agent/memory.py` | `_build_system_message` — 把 `state.focused_episode_id` / `state.last_enumeration_episodes` 注入 system prompt + `_ORDINAL_INSTRUCTION` 教 agent「第 N 集」對應 `last_enumeration_episodes[N-1]` |
| `backend/app/services/chat_agent/state.py` | `ChatSessionState` Redis-backed L1 anchor (FIFO 20 enumeration + focused episode TTL) |
| `backend/app/services/episode_finders.py` | 4 個 db helper: `find_episodes_by_guest` / `_by_topic` / `_by_date_range` / `find_by_ref` |

### Prod evidence（2026-05-23）

```
question:  "最新一集的來賓是誰？"
debug_trace.tool_calls: []                  # ← agent 沒呼叫任何 tool
answer:    "我目前無法確定最新一集的來賓資訊。可以麻煩提供更具體的集數或主題嗎？"
```

(evidence file: `/tmp/ordinal_evidence/曼報_latest_guest.json`)

### 設計師視角

- 既有 tool 都是「by 某種屬性 filter」(guest / topic / date / ref / id)；沒「by 排序＋取 top N」維度
- `find_episodes_by_date_range` 需 explicit `start`/`end` datetime，agent 沒能力可靠把「最新一集」翻成日期範圍
- multi-turn ordinal carry code path 看起來完整，但 memory 待驗證 → 不過早投入 effort

## Goals / Non-Goals

**Goals:**

- (A1) 新 tool `list_episodes(show_id, n, order, topic, year_start, year_end)` 上線後，prod chrome-devtools 重現「最新一集的來賓是誰？」query → debug_trace 至少 1 個 `list_episodes(show_id, n=1)` tool call，answer 引用真實 EP（之前曼報 prod 抓到的 EP127 或更新一集）。
- (A2) 同 tool 覆蓋「最舊 N 集」「2024 年最後一集歌單」「2023-2024 最舊一集」三個 query；最後一個含 topic + year_range AND filter。
- (A3) `find_episodes_by_date_range` 補 `order` + `limit` optional kwarg 後，「上週最新一集」「2024 年 3 月最舊一集」可用 explicit datetime range 解。
- (B1) Prod chrome-devtools 三節目（曼報 / 壹加壹電台 / 這又沒有很屌）各跑兩 turn 對話「歌單有哪幾集？」→「第三集是什麼內容？」確認 turn 2 第一個 tool call 是 `get_episode_summary(episode_id=<state.last_enumeration_episodes[2]>)` 而非 `find_episode_by_ref(ref='EP3')`。
- (C1) SYSTEM_PROMPT 補「事實 grounding 規則」段落上線後，重跑 `extended-multi-turn-40` 並用既有 LLM judge prompt 計分，severe rate 從 `enable-agentic-chat-default-on` archive 那輪的 **20% → ≤ 10%**（A1-style 預設目標，gate 通過即 pass）。
- 三件 fix 都附 prod evidence + 寫進 case study。

**Non-Goals:**

- 不開「最新 + agentic citation」這類新欄位（agent path 既有 citation 結構不動）。
- 不改 LLM judge prompt / 不換 judge model（保持跟 archive 那輪同 metric 對比）。
- 不動 4 個既有 finder 的 signature（除了 `find_episodes_by_date_range` 加 sort/limit）— `find_episodes_by_topic` / `_by_guest` / `find_by_ref` 不在本 change scope。
- 不引入新 RAG-only mode（譬如強制每個事實 claim 都要 tool citation）— 留給未來 R2.2 prompt 重做。
- 不動 `state.last_enumeration_episodes` FIFO / TTL 設計（chat-agentic-tool-routing 既有設計）。
- 不調 14 天觀察期 rollback threshold（5% failure-signal）— 那是另一條 runbook 的事。
- 不修 hallucination root cause level 2（譬如 retrieval 階段把相關 chunks 過濾乾淨）— 本 change 只在 generation 層加 prompt guard。

## Decisions

### D1 — 新 tool `list_episodes` 的 param surface

```
list_episodes(
    show_id: UUID,
    *,
    n: int = 5,                                      # max 20, raise validation error otherwise
    order: Literal['newest', 'oldest'] = 'newest',
    topic: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
) -> { episodes: list[EpisodeRef], n_returned: int, n_total_matched: int }
```

**`n` default 5**：跟既有 `find_episodes_by_topic` 預設拉 10 集對齊一半；user query「最新一集」最常見要 1-5 集。max=20 避免一次撈全 show（既有 EP 數最多 255）。

**`order` enum 兩值**：`'newest'` map 到 `ORDER BY published_at DESC NULLS LAST`，`'oldest'` 反過來。LLM 對兩值 enum 穩定。

**`topic` filter**：沿用 `find_episodes_by_topic` 既有 tsquery on `episode_description_chunks.tsv`（CJK simple_cjk analyzer，配合 `enumeration-rule-pattern-broaden` archive 的 jieba 切詞）。複用 helper，不重寫 retrieval。

**`year_start` / `year_end` 都 optional**：
- 都 None → 不加 year filter
- 都給且相等 → 單年（用 `year_start == year_end == 2024`）
- range → inclusive 兩端

用 `EXTRACT(YEAR FROM published_at AT TIME ZONE 'Asia/Taipei')` — 台灣場景 podcast 都以 Taipei 行事曆為主，跨年區段不會錯位。

**Return shape 多 `n_total_matched`**：給 agent 知道是否還有更多沒拉到（譬如「2024 歌單」其實有 8 集但只回 5 集），prompt 可教 agent 「如果 n_total_matched > n_returned 且使用者沒指定數量，回答時要說『目前列出 N 集，總共 M 集』」。

### D2 — `find_episodes_by_date_range` 補 sort/limit

```
find_episodes_by_date_range(
    db, show_id, start, end,
    *,
    order: Literal['newest', 'oldest'] = 'newest',   # NEW; backwards-compat default
    limit: int | None = None,                         # NEW; None = unbounded (既有行為)
)
```

`order` default `'newest'` — 既有調用方沒指定 ordering，hardcoded `ORDER BY published_at DESC` 在 `_DATE_SQL`，default `'newest'` 維持不變。

`limit` default `None` — 等同既有「不加 LIMIT」行為，現有 caller (`/query` rule-based path entity_filter) 不破壞。

SQL 在既有 `_DATE_SQL` template 加 `{order_clause} {limit_clause}` placeholder：

```sql
WHERE e.show_id = :show_id
  AND e.published_at >= :start
  AND e.published_at <= :end
ORDER BY e.published_at <order>
{LIMIT :limit}
```

### D3 — `list_episodes` 跟既有 finder 分工

| Query intent | Tool |
|---|---|
| 列「show 全集 by recency」(無 filter) | `list_episodes` 不帶 topic/year |
| 列「topic 全部符合」（無 sort/limit） | 既有 `find_episodes_by_topic`（無 limit default） |
| 列「topic + 最新 N 集」 | `list_episodes(topic=..., n=N)` |
| 列「topic + year_range 內最舊」 | `list_episodes(topic=..., year_start=..., year_end=..., order='oldest', n=1)` |
| 「上週 / 上個月」相對日期 + 限數量 | agent 自算 datetime → `find_episodes_by_date_range(start, end, limit=N)` |
| 「2024 整年」calendar year + sort | `list_episodes(year_start=2024, year_end=2024)` |
| 由 EP 編號 / 主題名 / 「最後一集」精確 ref | 既有 `find_episode_by_ref`（不變）|

SYSTEM_PROMPT 加分工指引（per D4 grounding 規則一起寫）。

### D4 — Hallucination grounding 規則插入位置與內容

`backend/app/services/chat_agent/prompts.py` 的 SYSTEM_PROMPT 既有結構（per `chat-tool-error-isolation` archive）：

```
[role 定義]
[tool routing guidance]
[tool error handling 規則]
```

新增「事實 grounding 規則」段落在 tool error handling 之後、tool 列表之前：

```
【事實 grounding 規則 — 重要】
回答中「絕對不能編造」以下 6 類內容；它們只能直接引用 tool result 或來自使用者輸入：
1. 節目名稱（show title）
2. 來賓 / 嘉賓姓名（host / guest name）
3. EP 編號（episode number）
4. 集數標題（episode title）
5. 來賓具體 quote（引號內的話）
6. 統計數字（"X 集"、"N 次提到"、"總共 M 分鐘"）

如果 tool 沒返回足夠資訊回答以上 6 類，請明確說「資料不足，無法確認」而非自行推測。

未列出的內容（譬如節目整體傾向、主題評論、跨集主題分析）可從 tool result 合理推論，但結尾請加「以上分析基於 tool 取得的內容，請以節目實際內容為準」disclaimer。
```

**Why 不分 two-tier 規則樹**：LLM 對明確 enumeration 執行率比 nested branching 高（per `chat-tool-error-isolation` 經驗）。

**Why 6 類**：基於 `enable-agentic-chat-default-on` archive LLM judge 那輪 8 條 severe hallucination 的歸類（譬如「節目《也好吃》」是 show name 編造、「楊大正說...」是 quote 編造）。

### D5 — Multi-turn ordinal carry verify methodology

不寫 code。只用 prod chrome-devtools-mcp + admin E2E backdoor session 跑：

```
Session 共用，三節目分別跑：
- 曼報 (show_id=88702ed8-...)
- 壹加壹電台 (show_id=待查)
- 這又沒有很屌 (show_id=待查)

對每個節目:
  turn 1: question="歌單有哪幾集？"  
          → 預期 list of episodes 或「沒有歌單集數」
          → 從 ?debug_trace=true 確認 tool_calls 含 find_episodes_by_topic(topic='歌單')
          → 從同 trace 確認後續 state.last_enumeration_episodes 有寫入 (>= 1 個 ep_id)
  
  turn 2: question="第三集是什麼內容？"  (session_id 同 turn 1)
          → 預期 agent 第一個 tool call 是 get_episode_summary(episode_id=<某 UUID>)
          → 該 UUID 必須是 turn 1 enumeration list 的 [2] (index 2, 第三集)
          → 若 agent 改用 find_episode_by_ref(ref='EP3') 或 ref='3' → fail
```

**Pass 條件**：三節目至少兩個通過 turn 2 第一個 tool call 是 `get_episode_summary` 用 index-correct ep_id（單節目偶然 false positive 概率不高，但兩 / 三節目都對才算 robust）。

**Fail 處理**：明確列出 root cause（譬如 `_ORDINAL_INSTRUCTION` 文字 LLM 沒讀懂 / state 沒寫回 / FIFO TTL 過早 expire）+ 給後續 sub-change 草稿，不在本 change 修。

### D6 — Test 戰術

**Unit test (Python)**：
- `test_list_episodes_recency.py`：
  - Fixture：seed 5 episode 給虛擬 show，published_at 跨 2023-2025
  - `test_default_n_newest`: 期望回 5 集且 sorted DESC
  - `test_order_oldest`: 期望 sorted ASC
  - `test_topic_filter`: 加 topic='AI'，期望只回 topic 命中集數
  - `test_year_range_single`: year_start=year_end=2024，期望只 2024 集數
  - `test_year_range_inclusive`: year_start=2023, year_end=2024，期望兩年全
  - `test_n_total_matched`: 種 8 集，n=5，期望 n_returned=5 / n_total_matched=8
  - `test_n_max_20`: n=25，期望 validation error 或 clip 到 20
- `test_chat_agent_grounding_prompt.py`：snapshot SYSTEM_PROMPT 含 6 類 explicit「不能編造」字串

**Prod chrome-devtools-mcp scenario**：
- (A) 三 recency query (最新三集 / 最舊五集 / 2024 年最後一集歌單) 各跑一次，trace 含 list_episodes tool call
- (B) D5 描述的兩 turn 對話三節目
- (C) 跑「介紹一下這個節目」+ 「最新一集評論什麼」之類開放 query，撈 answer 字面看是否含未在 tool result 出現的 show/guest/EP 編號

**Eval**：跑 `backend/scripts/run_chat_agent_eval.py` 用 `extended-multi-turn-40` dataset + 既有 LLM judge prompt 比對 archive 那輪結果，severe rate 從 20% → ≤ 10%。Recall@5 + answer_match 不應 regression。

## Implementation Contract

**Behavior**：

- `list_episodes` tool 在 chat agent 11 個既有 callable tool 旁新增第 12 個；OpenAI tool schema 自動 derive from Pydantic input model。
- 「最新一集 / 最舊一集 / 2024 年歌單最舊一集」等 query 改由 `list_episodes` 處理；agent 應在 single-round 內就完成 tool call，不再 multi-round 試錯 / 直接放棄。
- `find_episodes_by_date_range` 既有 caller（rule-based path）行為不變（default `order='newest'` + `limit=None`）；agent path 可選擇傳 `limit=N` 取 top N。
- SYSTEM_PROMPT 在 multi-turn answer 中明確避開 6 類編造；當 tool 沒給足夠資訊時改說「資料不足」而非推測。
- Multi-turn ordinal carry verify-only — 無 code 變更，但 prod evidence 寫進 case study。

**Interface / data shape**：

```python
# list_episodes 輸出 shape
{
  "episodes": [
    { "episode_id": "<uuid>", "title": "...", "published_at": "ISO 8601",
      "duration_seconds": float, "description_snippet": "..." },
    ...
  ],
  "n_returned": int,
  "n_total_matched": int,
}

# find_episodes_by_date_range 輸出 shape — 維持既有 list[EpisodeRef]，
# 不加 n_total_matched (避免 backward-compat 破壞)
```

```python
# 新 SYSTEM_PROMPT 段落（zh）
"""
【事實 grounding 規則 — 重要】
回答中「絕對不能編造」以下 6 類內容；它們只能直接引用 tool result 或來自使用者輸入：
1. 節目名稱（show title）
2. 來賓 / 嘉賓姓名（host / guest name）
3. EP 編號（episode number）
4. 集數標題（episode title）
5. 來賓具體 quote（引號內的話）
6. 統計數字（"X 集"、"N 次提到"、"總共 M 分鐘"）

如果 tool 沒返回足夠資訊回答以上 6 類，請明確說「資料不足，無法確認」而非自行推測。

未列出的內容（譬如節目整體傾向、主題評論、跨集主題分析）可從 tool result 合理推論，但結尾請加「以上分析基於 tool 取得的內容，請以節目實際內容為準」disclaimer。
"""
```

**Failure modes**：

- `list_episodes` 拿到 n > 20：validation 階段擋下，raise standard tool error envelope `{ok:false, kind:'validation', user_hint:'最多一次列 20 集'}`。
- `list_episodes` year_start > year_end：raise validation error。
- `list_episodes` topic + year_range 都給但無命中：回 `{episodes:[], n_returned:0, n_total_matched:0}`，agent 應改答「2024 沒有歌單相關集數」。
- `find_episodes_by_date_range` limit=0：raise validation error（必須 None 或 ≥1）。
- SYSTEM_PROMPT 加 grounding 段落後若 agent 觸發 token budget overflow：既有 `agent-token-budget-and-tool-truncate` 機制承接（pop 最舊 tool result）。
- Multi-turn carry verify fail：明確 surface 失敗集數 + tool_calls trace + 對應 sub-change 草稿，不阻斷本 change archive。

**Acceptance criteria**：

- Unit test 全綠：`pytest tests/test_list_episodes_recency.py tests/test_chat_agent_grounding_prompt.py` 7+ test all pass。
- Prod chrome-devtools scenario A 三 query trace 各有 1+ `list_episodes` tool call；answer 引用實際存在的 episode（用 episode_id 對 DB cross-check）。
- Prod chrome-devtools scenario B 三節目 turn 2 至少 2/3 用 `get_episode_summary` 帶 index-correct ep_id。
- Eval rerun: `aggregate.answer_quality_severe_rate ≤ 0.10`（vs archive baseline 0.20）；`recall_at_k_mean ≥ 0.40`（不 regression）；`answer_match_mean ≥ 0.55`。

**Scope boundaries**：

- **In scope**:
  - backend/app/services/episode_finders.py（新增 `find_episodes_by_recency` helper + `find_episodes_by_date_range` 補 order/limit）
  - backend/app/services/chat_agent/tools.py（新增 `_list_episodes` + Pydantic input model + 註冊進 tool registry）
  - backend/app/services/chat_agent/prompts.py（SYSTEM_PROMPT 加 grounding 段落 + tool routing 分工 hint）
  - backend/tests/test_list_episodes_recency.py（new）
  - backend/tests/test_chat_agent_grounding_prompt.py（new）
  - docs/case-studies/agentic-prompt-grounding-and-ordinal-tool-2026-05-24.md（new, not git-tracked）
- **Out of scope**:
  - 4 個既有 finder 除 `find_episodes_by_date_range` 之外的 signature
  - `state.py` / `memory.py` 的 carry 邏輯
  - Agent loop / token budget / tool dispatch / state TTL
  - Frontend（agent 回的 episodes 結構 frontend 還是用既有 enumeration_episodes 顯示）
  - LLM judge prompt / dataset / runner

## Risks / Trade-offs

- **R1 — `list_episodes` 跟 `find_episodes_by_topic` 重複**：「歌單哪幾集」可走 `list_episodes(topic='歌單')` 也可走 `find_episodes_by_topic(topic='歌單')`。Trade-off：兩條 path 都 work，prompt 引導 agent 「需要 sort/limit 時用 list_episodes、要列全部時用既有」。若 agent 誤選 path 也不會錯結果，只是 limit 不同。可接受。
- **R2 — `EXTRACT(YEAR FROM ... AT TIME ZONE 'Asia/Taipei')` 寫死台灣時區**：未來若 podcast 來源跨多時區 / 多語系 user 可能誤判跨年 episode。本專案目前 zh-tw only，可接受；未來開國際化 change 時再 generalize（譬如改用 `settings.default_timezone`）。
- **R3 — Hallucination prompt 加長可能擠到既有 context budget**：SYSTEM_PROMPT 增加 ~250 chars，相對既有 ~3000 chars 不大。token budget guard (`agent-token-budget-and-tool-truncate`) 在 100K threshold，影響可忽略。
- **R4 — 6 類「不能編造」清單可能太嚴讓 agent 對開放 query 過度保守**：可能出現「我無法確認 X」變多。試 eval 跑完看 answer_quality / answer_match 兩個 metric 是否一起降；若降太多需 prompt fine-tune（譬如加「但可以基於 tool 結果合理推測」軟化）。
- **R5 — Multi-turn carry verify fail 但無時間在本 change 修**：scope 不含實際 fix，verify fail 只 surface root cause + 草稿後續 sub-change。trade-off：本 change 可能 archive 但 carry 仍 broken；fail-fast surface 比悄悄帶過好。
- **R6 — `list_episodes` 跟既有 11 tool 命名衝突或 LLM 混淆**：tool name 改 `list_episodes` 而非 `find_episodes_*` 系列，目的就是讓 LLM 看到「list」字面就連結到「列 + sort + limit」直覺。但 11 tool 中也有「find_episodes_*」系列，可能 agent 不確定該用哪個。靠 prompt 分工指引 + Pydantic schema 的 description 字段降低混淆，但仍有 tail risk。Eval rerun 順手看 tool_required_hit 是否 regression。
