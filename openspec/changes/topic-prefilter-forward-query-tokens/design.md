## Context

b23 端到端三層：①routing（b22 已部署、正確 force 到 `search_with_topic_prefilter`）／②trigger（本 change）／③ranking（hybrid union 已部署、DB-proven）。本 change 修 ②：把 `inp.query` 轉發進候選選集，讓 transcript-aware 觸發 gate 在 agent 給的 `topic` 太薄（gpt-5.1 穩定只放單一實體 token，如「Leo王」）時，改用 query 的鑑別 token 開 gate。

## Goals / Non-Goals

In scope：
- `_search_with_topic_prefilter` 把 `inp.query` 傳進 `find_episodes_by_topic_with_source`。
- `find_episodes_by_topic_with_source` 在 topic 鑑別 token <2 時，改用 topic ∪ query 的鑑別 token 作為 transcript-aware 路徑的「生效 token」（gate + tsquery + coverage `:tokens` 同源）。

Out of scope：
- 不改 agent prompt / tool description（不靠模型自律把更多字放 topic）。
- 不改 b22 routing、不改 hybrid union 排序 SQL、不改 chunk 召回 / voyage rerank。
- 不改 `topic_index`（title/desc）與 guest-dispatch 路徑（仍只用 topic）。
- 不改 `find_episodes_by_recency` 與舊 callable `find_episodes_by_topic`（無 `_with_source`）的行為。

## Decisions

### D1：query 轉發點 = tool callable → finder 新增 optional 參數
`_search_with_topic_prefilter`（chat agent tools 模組）已持有 `inp.query`；改為呼叫 `find_episodes_by_topic_with_source(db, show_id, [inp.topic], query=inp.query)`。`find_episodes_by_topic_with_source` 新增 keyword-only optional 參數 `query: str | None = None`，預設 `None`。所有既有呼叫點（包含 `find_episodes_by_topic` wrapper 與 `_find_episodes_by_topic` 工具）不傳 query → `None` → 行為與現況位元等價。理由：訊號（query）已在 tool 入參，最小改動轉發即可，不需新資料流或 DB 欄位。

### D2：token 推導策略 = fallback-only（topic<2 才用 query），非 always-union
生效 token 規則：
- 令 `topic_tokens = _discriminating_tokens(expand(topic))`（沿用既有 expand：jieba、len≥2、`TOPIC_STOPWORDS`、`get_show_name_terms()` 移除）。
- 若 `len(topic_tokens) >= 2`：生效 token = `topic_tokens`（**與現況完全相同，query 不介入**）。
- 否則若有 query：生效 token = `_discriminating_tokens(expand(topic) + expand(query))`（dedup、保序）。
- 否則（無 query 或仍 <2）：生效 token = `topic_tokens`（<2 → gate 不開，bit-equivalent 現況）。

理由（為何 fallback-only 而非 always-union）：當 topic 已 ≥2 個鑑別 token，agent 給的是聚焦主題（enumeration 題如「高雄 美食」走這條），把整句 query 併進來會引入通用詞噪音、且改動已驗證行為。fallback-only 把 query 的介入嚴格限制在「現況已壞」的 thin-topic 情形，**enumeration 題 topic 恆 ≥2 → 永不觸發 query fallback → 零回歸**，blast radius 最小。

### D3：over-select 邊界
- query fallback 帶進的 token 仍走**同一個** ≥2 gate 與**同一個** hybrid union（2×`transcript_prefilter_cap` 上限）。episode 數上限不變。
- 通用詞汙染只可能發生在 thin-topic narrative 題自身（那正是要救 EP107 的題），且下游 voyage rerank 吸收 2×cap 候選；enumeration 題因 topic≥2 不受影響。
- 不對 query token 設硬性數量上限（episode cap 已是 over-select 主防線）；但生效 token 經 `_discriminating_tokens` 過濾（len≥2 + stopword + show-name 移除）後 dedup，避免 tsquery 退化。

### D4：tsquery / coverage `:tokens` 同源不變式（沿用 hybrid D2）
transcript-aware 路徑觸發後，`tsquery_text`（OR-join）與 `:tokens`（coverage arm 陣列）一律由 D2 算出的「生效 token」建構，兩者同源——維持 `" | ".join(tokens) == tsquery_text` 不變式（既有測試 `test_transcript_query_binds_tokens_param` 斷言）。

### D5：flag
不新增 flag。query fallback 由既有 `enable_transcript_topic_prefilter` 涵蓋（flag off → transcript 路徑整段不執行 → query 是否轉發無影響，候選與現況位元等價）。

## Risks / Trade-offs

- 風險：thin-topic narrative 題候選集變大（query 帶進更多 token → 命中更多集）。緩解：episode 仍受 2×cap 限制、下游 voyage rerank 吸收；且這正是目標題型，擴大召回是預期。
- 風險：query 含與主題無關的閒聊字 → coverage arm 撈進無關集。緩解：`_discriminating_tokens` 已濾停用詞 / 短詞 / show-name；殘餘噪音由 rerank 收斂。驗收用 DB probe 量「高雄美食」不受影響（topic≥2 不觸發）+ b23 候選含 EP107。

## Implementation Contract

- `find_episodes_by_topic_with_source` 簽章新增 keyword-only `query: str | None = None`。預設 `None` 時，生效 token = `topic_tokens`，行為與本 change 前位元等價（既有所有呼叫點不受影響）。
- 觀察行為：當 `topic_tokens` <2 且 `query` 非空且 `_discriminating_tokens(expand(topic)+expand(query))` ≥2 → transcript-aware 路徑觸發，`prefilter_source` 可為 `transcript_index` 或 `merged`，且 `tsquery_text` / `:tokens` 由該組生效 token 構成。
- 當 `topic_tokens` ≥2：忽略 `query`，生效 token = `topic_tokens`，與現況輸出逐位相同。
- `_search_with_topic_prefilter` 傳 `query=inp.query`；`_find_episodes_by_topic`（find_episodes_by_topic 工具）與 `find_episodes_by_topic` wrapper 不傳 query。
- 失敗模式：`query=None` 或空字串 → 視同未提供 query，走 topic-only 規則。
- 驗收標準：見 tasks——(a) 單元測試覆蓋三分支（topic≥2 忽略 query / topic<2 用 query 開 gate / query=None bit-equivalent）；(b) DB probe 雙向（b23 含 EP107、高雄美食 EP85/EP140 不掉且不暴增）；(c) prod b23 smoke EP107 命中 >0 且 `prefilter_source=transcript_index`。
- Scope 邊界：只動 `tools.py` 的 `_search_with_topic_prefilter` 呼叫與 `episode_finders.py` 的 `find_episodes_by_topic_with_source` token 推導；不動 SQL 結構、不動 `topic_index` / guest / recency 路徑。
