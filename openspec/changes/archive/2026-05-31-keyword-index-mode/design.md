## Context

PodcastRAG 既有搜尋 `POST /shows/{show_id}/search`（`backend/app/api/query.py:148`）使用 embedding + RRF 做語意命中，對逐字精準命中（人名 / 節目特定詞 / 標籤）表現不穩。三個 tsvector 欄位皆已存在且由 jieba 預先 tokenize：

- `episodes.title_tsvector`（`backend/app/models/episode.py:51`）
- `episode_description_chunks.text_tsvector`（`backend/app/models/episode_description_chunk.py:45`）
- `transcript_chunks.text_tsvector`（`backend/app/models/transcript_chunk.py:36`）

`backend/app/services/rag.py` 已有 jieba → tsquery escape helper（escape 規則在 docstring `rag.py:212` / 註解 `rag.py:226`）可直接借用。

**並行 change `landing-and-mode-orchestration-redesign` 已 ship（archive `2026-05-23-landing-and-mode-orchestration-redesign` + hotfix `2026-05-23-landing-redesign-hotfix-transcript-and-audio`），本 change 依賴的前置已就緒（2026-05-31 ingest 驗證）：**

- 三 tab shell 存在：`src/QueryPage.jsx` 的 `activeTab` / `setActiveTab` / `TABS = [index, semantic, chat]` 固定順序，未登入預設 `index` tab（`QueryPage.jsx:231`）。
- **索引 tab 目前是「即將推出」placeholder**（`QueryPage.jsx:490` 輸入框 disabled、`:555` 空狀態文案）— 本 change 補完的就是這塊。
- sticky audio player 上線：`AudioPlayerProvider`（`App.jsx:311`）+ `useAudioPlayer()` hook；跳播 API 是 `audio.playFromTime(episode_id, start_time, { audio_url })`（既有用法見 `QueryPage.jsx:462`），**不是泛用 seek**。
- 跨 tab 共用輸入字串 state `queryText`（`QueryPage.jsx:233`）已存在，切 tab 時自動保留輸入 — mode switcher 不需自行搬運 query。
- `GET /shows/{show_id}/trending-queries` 已實際存在（`backend/app/api/events.py:102`），EmptyState 範例查詢可直接打，不再是「若 Change 1 上線才有」的條件依賴（保留寫死 fallback 以防空回應）。
- 既有單色關鍵字高亮 precedent 在 `QueryPage.jsx:940`（`<mark style={{ background: TOKEN.accent+'44' }}>`），本 change 的兩色 `highlightTerms` 為其延伸。

## Goals / Non-Goals

**Goals:**

- 對單一 show 提供「嚴格 AND 多關鍵字 + 三池跨欄位 episode 命中」的索引搜尋。
- 三段式 sectioned 結果（T1 / T2 / T3）一次 CTE 取出，避免 round-trip。
- T3 fallback 僅當 T1+T2 完全 0 才觸發，避免污染高品質結果。
- T2 在 T1 強命中時自動 collapse 為精簡 chip，admin 可調 threshold。
- 結果頁能在不重打 endpoint 的情況下做 incremental「再來 5 段／集」，硬上限 100。

**Non-Goals:**

- 不取代既有語意 endpoint，不重做 chunk 切割與 embedding pipeline。
- 不引入新 index / schema migration（重用既有 tsvector + jieba dictionary）。
- 不做付費 / quota gating；索引模式不打 LLM。
- 不實作 phrase / 引號 / OR toggle 等查詢語法（user 明示移除）。
- 不動 Change 1 範圍的 HomePage / 對話 source / Lock card / sticky audio / paragraph aggregation / Hybrid C semantic 渲染。

## Decisions

### 新 endpoint 而非延伸既有 `/search`

選 `POST /shows/{show_id}/keyword-search` 而非加 `?mode=keyword` query param 到既有 endpoint。理由：

- 既有 `/search` 回傳 `PublicSearchResponse`（chunk-flat 結構），與 sectioned T1/T2/T3 形狀差異大，硬塞會逼前端做型別判斷。
- 新 endpoint 可獨立加 admin threshold、獨立 rate-limit、獨立 schema 演進。
- Router 結構對齊 `backend/app/api/query.py` 的 `/shows/{show_id}/*` 慣例（新檔 `backend/app/api/keyword_search.py`）。

替代：在 `/search` 加 `mode` 欄位 union response → 否決（型別污染、難演進）。

### Query 前處理：jieba 切詞 + 標點去除 + 永遠 AND

- 接收原始字串 → `app.services.tokenizer.tokenize()` 切詞 → 過濾單字符標點與 stopword → 得到 `terms: list[str]`，去重保序。
- 若 `terms` 為空 → 回 422 `EMPTY_QUERY`。
- 不解析引號、不解析 `OR`、不解析 `-`（user 明示）。
- T1 / T2 一律 AND，T3 一律 OR — 由後端 SQL 決定，前端無 toggle。

### SQL CTE：T1 + T2 一次取，T3 條件 fallback

採單一 SQL 包三個 CTE，避免兩次 round-trip。**下方 CTE（含 `bool_or` pivot）為示意，表達 T1/T2 語意**；實際 T2 的「每集每池命中」依下方決策（line「`pool_hits` 在 service 層以 Python…」）改在 service 層用 per-term query + Python union 計算，不在 SQL 端做 `bool_or` 動態 pivot（見 task 2.2）：

```
WITH
  -- T1: 同 chunk AND 命中所有詞
  t1 AS (
    SELECT tc.id AS chunk_id, tc.episode_id, tc.start_time, tc.end_time,
           tc.text, ts_rank(tc.text_tsvector, q_and) AS rank
    FROM transcript_chunks tc
    JOIN episodes e ON e.id = tc.episode_id
    CROSS JOIN to_tsquery('simple', :q_and) AS q_and
    WHERE e.show_id = :show_id
      AND tc.text_tsvector @@ q_and
    ORDER BY rank DESC
    LIMIT :section_limit          -- 預設 100
  ),
  -- 每集每池命中字計數（pivot）
  pool_hits AS (
    SELECT e.id AS episode_id,
           bool_or(e.title_tsvector @@ to_tsquery('simple', :term))     AS title_hit,
           bool_or(edc.text_tsvector @@ to_tsquery('simple', :term))    AS desc_hit,
           bool_or(tc.text_tsvector  @@ to_tsquery('simple', :term))    AS tx_hit,
           :term AS term
    FROM episodes e
    LEFT JOIN episode_description_chunks edc ON edc.episode_id = e.id
    LEFT JOIN transcript_chunks tc ON tc.episode_id = e.id
    WHERE e.show_id = :show_id
    GROUP BY e.id, term
  ),
  -- T2: 每個 term 至少在某一池命中（跨池 AND on terms, OR on pools）
  t2 AS (
    SELECT episode_id,
           count(*) FILTER (WHERE title_hit) AS title_n,
           count(*) FILTER (WHERE desc_hit)  AS desc_n,
           count(*) FILTER (WHERE tx_hit)    AS tx_n
    FROM pool_hits
    WHERE title_hit OR desc_hit OR tx_hit
    GROUP BY episode_id
    HAVING count(*) FILTER (WHERE title_hit OR desc_hit OR tx_hit) = :term_count
    LIMIT :section_limit
  )
SELECT ... FROM t1, t2;
```

- `:q_and` = `term1 & term2 & ...`（jieba 切詞後以 `&` join 並 escape tsquery operators，沿用 `rag.py:212` 的 escape 邏輯）。
- `pool_hits` 在 service 層以 Python 對每個 term 各跑一次 query 並 union 結果到 `t2` set，避免動態 SQL 拼出 N 次 lateral join；單 show 範圍小（episodes 數百級），acceptable。
- T3 fallback：若 `len(t1) + len(t2) == 0`，再單獨跑一次 OR query（`term1 | term2 | ...`）在 transcript_chunks，回小型 chunk list（上限 50）。

替代：用 `websearch_to_tsquery` → 否決（不支援 jieba 自訂 dict 的同詞性質、AND 行為不一致）。

### T2 collapse threshold

- Service 接 admin setting key `keyword_t2_collapse_threshold`（int，預設 10，admin UI 可改）。
- 若 `len(t1) >= threshold`，response 仍照算 T2 但加 `"collapsed": true` flag，前端只顯示「+N 集亦有命中」chip 而非展開卡片清單。
- 不在 SQL 端 skip T2（讓 admin 切 threshold 不用重打 endpoint 也能觀察）。

### Response Schema

```json
{
  "query": "原始字串",
  "terms": ["term1", "term2"],
  "mode": "keyword",
  "t1": {
    "section": "chunk-and",
    "total": 23,
    "items": [
      {
        "chunk_id": "uuid",
        "episode_id": "uuid",
        "episode_title": "EP.123",
        "start_time": 145.3,
        "end_time": 162.0,
        "text": "...",
        "hits": [{"term": "term1", "positions": [12, 80]}, ...]
      }
    ]
  },
  "t2": {
    "section": "episode-and",
    "total": 5,
    "collapsed": false,
    "items": [
      {
        "episode_id": "uuid",
        "episode_title": "EP.45",
        "pool_counts": {"title": 1, "description": 2, "transcript": 7}
      }
    ]
  },
  "t3": null
}
```

- T3 出現時 `t1.total == 0 && t2.total == 0`，`t3.items` 為輕量 chunk hits。

### Pagination

- Request 接 `offset_t1`, `offset_t2`（int，預設 0），每呼叫回最多 `section_limit`（預設 25 per request，硬上限 100 total per section by service-level guard）。
- 前端「顯示更多 5 段／集」=> 用當前 offset + 5 再打一次同 endpoint，merge 進 state。
- Section 累積到 100 後前端隱藏「顯示更多」btn。

### 兩色高亮分配規則

- Service 回 `terms` 為 jieba 切詞後保序去重 list。
- 前端按 `terms` 順序輪替指派色碼：`idx % 2 === 0` → 橘 `#f97316`、`idx % 2 === 1` → 青 `#06b6d4`（沿用 TOKEN.accent 體系外加兩色 hi-vis）。
- 同 term 同色，多 term 多色但只兩色循環，避免色彩過載。
- 高亮 helper：`highlightTerms(text, terms, colorMap)` 回傳 React fragment array，case-insensitive substring match（中文無 case 但 helper 保留參數），命中段以 `<mark style={{background, color}}>` 包裹。

### 前端 sectioned 渲染元件結構

```
<KeywordResults result={resp} terms={terms} onMoreT1 onMoreT2 onJumpTo>
  ├─ <T1ChunkSection items={resp.t1.items} terms={terms} />
  │     └─ <ChunkCard>（顯示命中前後一句 + 「上下 5 段」展開 + 跳播 btn）
  ├─ <T2EpisodeSection items={resp.t2.items} collapsed={resp.t2.collapsed} />
  │     └─ collapsed=true → 單一 chip「+5 集亦有命中」
  │     └─ collapsed=false → <EpisodeCard>（三池分計數 + 「展開查看各段」）
  ├─ <T3FallbackSection items={resp.t3?.items} />（僅當 T1+T2=0）
  └─ <BottomModeSwitcher onSwitchMode={fn} />（永遠顯示）
```

- `<BottomModeSwitcher>` 是新的純展示 chip，**接 prop `onSwitchMode(tab)` 由 `QueryPage` 傳入並 wire 到既有 `setActiveTab('semantic' | 'chat')`**（`QueryPage.jsx:231`）；query 字串切 tab 後由既有跨 tab 共用 state `queryText`（`QueryPage.jsx:233`）自動保留，switcher **不需自行搬運 query**。
- 0 結果：`t1.total + t2.total + (t3?.total ?? 0) === 0` → 渲染 `<EmptyState>` 含 mode switcher chip 與 3 個範例查詢建議（打 `GET /shows/{id}/trending-queries`，該 endpoint 已上線於 `events.py:102`；空回應或非 200 時 fallback 寫死 3 筆）。

### Admin Setting

⚠️ **2026-05-31 ingest 校正**：`app_settings` 並非 key-value store，而是**結構化單列表**（`AppSettings` model，`backend/app/models/app_settings.py`，現有欄位 `max_concurrent_transcriptions` / `monthly_cost_cap_usd`）。新增 threshold 需動四處：

- DB：新增欄位 `keyword_t2_collapse_threshold INT NOT NULL DEFAULT 10` → 一支單欄位 alembic migration。
- Model：`AppSettings` 加 `keyword_t2_collapse_threshold: Mapped[int]`（`nullable=False, default=10`）。
- Schema：`AppSettingsOut` 加 `keyword_t2_collapse_threshold: int`；`AppSettingsUpdate` 加 `keyword_t2_collapse_threshold: int | None = Field(default=None, ge=1)`（沿用既有 `backend/app/schemas/settings.py` 的 Field 驗證模式）。
- Endpoint：既有 `GET` / `PUT /admin/settings`（`backend/app/api/settings.py`）自動涵蓋新欄位，無需新增 route。
- 預設值 10，UI 文案「索引模式：T1 超過此數則 T2 折疊為 chip」。

## Implementation Contract

**Observable behavior**

- 對單一 show，使用者送出多詞查詢，後端回三段式結果；嚴格 AND 不會把只命中部分詞的 chunk 收進 T1，也不會把只命中部分詞的 episode 收進 T2。
- T1+T2 都 0 時，response `t3` 物件非 null 且包含 ≥1 hit；否則 `t3 === null`。
- T1 命中數 ≥ admin threshold 時，response `t2.collapsed === true`，前端只顯示 chip。
- 前端結果頁所有 chunk / episode 卡片內，命中詞以兩色（橘 / 青）輪替 `<mark>` 高亮，同一 term 始終同色。

**Interface**

- `POST /shows/{show_id}/keyword-search`
  - Body：`{ "query": str, "offset_t1": int = 0, "offset_t2": int = 0, "limit": int = 25 }`
  - 200：上文 Response Schema
  - 422 `EMPTY_QUERY`：jieba 切完後 `terms` 為空。
  - 404 `SHOW_NOT_FOUND`：show_id 不存在。
- `GET /admin/settings` / `PUT /admin/settings`：新增 `keyword_t2_collapse_threshold` key（int，預設 10）。

**Failure modes**

- jieba 切完空字串 → 422，不打 DB。
- DB query timeout（>5s）→ 503 `KEYWORD_SEARCH_TIMEOUT`，前端顯示「搜尋逾時，請縮短關鍵字」。
- T3 fallback 仍 0 hit → 200 + 空結果 + `EmptyState` 含 mode switcher chip。

**Acceptance criteria**

- 新 endpoint 通過 unit test：(a) AND 嚴格、(b) 三池 union 邏輯、(c) T3 僅在 T1+T2=0 時填、(d) collapse threshold 行為。
- `pytest backend/tests/test_keyword_search.py` 全綠。
- Frontend 手動驗證：在 prod 跑「世運 滅火器」「歌單」「馬世芳」三組查詢，T1/T2/T3 渲染正確、高亮兩色、incremental「再來 5 段」可達 100。
- Admin 改 `keyword_t2_collapse_threshold` 後新查詢立即生效（無需 restart）。

**Scope boundaries**

- **In scope**：本 design 列出的 endpoint、service、schema、admin setting、`<KeywordResults>` 與其子元件、`src/QueryPage.jsx` 索引 tab 接線。
- **Out of scope**：HomePage、對話 source、Lock card、sticky audio player、paragraph 聚合、語意 mode Hybrid C 渲染、tab shell 本身、付費 / quota gating。

## Risks / Trade-offs

- [Per-term `pool_hits` N 次 query] → 單 show episodes ≤500 級、tsvector index 已存在，實測單 query <50ms × 5 terms = 250ms，acceptable；若日後 show 變大改 lateral subquery。
- [T2 計算成本高但顯示被 collapse] → 接受 trade-off：admin 想觀察 threshold 效果需要看得到 total；若效能成問題再加 `?compute_t2=false` short-circuit。
- [兩色高亮對色盲使用者不友善] → 同時加 `<mark>` 框線粗細區隔（橘=實線、青=虛線下劃線），不純靠色彩。
- [前端 incremental paginate 與 T1 collapse 互動] → 規則：T1 達 threshold 後 T2 永遠 collapsed，使用者按 chip 才展開（展開時 fetch 完整 T2）。
- [tsvector 沒涵蓋新發音 / 新詞] → 沿用 `tokenizer-dictionary` capability 的自訂 dict 流程，本 change 不擴；admin 加詞後需 reindex 既有 chunks（既有任務）。
