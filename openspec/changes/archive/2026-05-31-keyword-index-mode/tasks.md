## 1. Backend: jieba 前處理與 query 解析（query 前處理：jieba 切詞 + 標點去除 + 永遠 AND）

實作 spec Requirement「Keyword search endpoint with strict AND semantics」中關於 tokenization 與不解析 OR/quote/`-` 的部分。

- [x] 1.1 在 `backend/app/services/keyword_search.py` 新增 `parse_query(raw: str) -> list[str]`，行為：呼叫 `app.services.tokenizer.tokenize()` 切詞、去除單字符標點與 stopword、保序去重，回 `terms`；空 list 視為合法回傳值由 caller 處理（對應 Requirement「Keyword search endpoint with strict AND semantics」的「永遠 AND、不解析 OR/quote」契約與「query 前處理：jieba 切詞 + 標點去除 + 永遠 AND」design 決策）。驗證：新檔 `backend/tests/test_keyword_search_parse.py` 包含 (a) 「！！！」→ `[]`、(b) 「馬世芳 馬世芳 滅火器」→ `["馬世芳","滅火器"]`、(c) 「歌單" OR 滅火器」→ jieba 切完不含引號與 `OR` 字面 token；`pytest backend/tests/test_keyword_search_parse.py -q` 全綠。

- [x] 1.2 在同檔加 `build_tsquery_and(terms)` 與 `build_tsquery_or(terms)`，回 `& ` / `| ` join 並 backslash-escape tsquery operator `&|!()<:>\`（比 `rag.py:226` 的 space-replacement 嚴格——保留 literal term 而非拆字；2026-05-31 apply 校正，符合 verification 的 `b\)c`）。驗證：unit test `test_keyword_search_parse.py::test_tsquery_build` 對 `["a","b)c"]` 產出 `'a & b\\)c'`（AND）與 `'a | b\\)c'`（OR）。

## 2. Backend: SQL CTE 與三池查詢（SQL CTE：T1 + T2 一次取，T3 條件 fallback）

實作 spec Requirements「T1 same-chunk AND section」、「T2 cross-pool episode AND section」、「T3 OR fallback section」。

- [x] 2.1 在 `backend/app/services/keyword_search.py` 新增 `query_t1(db, show_id, terms, offset, limit) -> tuple[list[T1Hit], int]`（對應 Requirement「T1 same-chunk AND section」與「SQL CTE：T1 + T2 一次取，T3 條件 fallback」design 決策），行為：對 `transcript_chunks JOIN episodes` 跑 `text_tsvector @@ to_tsquery('simple', :q_and)`，依 `ts_rank` desc 排序，回 `(items[offset:offset+limit], min(total,100))`。驗證：integration test 在 fixture show 中種 3 chunk（2 全命中 1 部分命中），assert 回 2 items 且部分命中 chunk 不在 list。

- [x] 2.2 在同檔新增 `query_t2(db, show_id, terms, offset, limit) -> tuple[list[T2Hit], int]`（對應 Requirement「T2 cross-pool episode AND section」），行為：對每個 term 各跑一次三池命中 query（title / description_chunks / transcript_chunks），在 Python 層計算「每集是否所有 term 都至少在某一池命中」，回符合的 episode list + `pool_counts`。驗證：integration test 種 episode A（title 含 termA、transcript 含 termB）與 episode B（只 title 含 termA），assert A 入選且 `pool_counts.title>=1 and pool_counts.transcript>=1`，B 不入選。

- [x] 2.3 在同檔新增 `query_t3(db, show_id, terms, limit=50)`（對應 Requirement「T3 OR fallback section」），行為：對 `transcript_chunks` 跑 `text_tsvector @@ to_tsquery('simple', :q_or)`，回最多 50 hits。驗證：unit test assert query SQL 使用 OR-joined tsquery 字串。

- [x] 2.4 加 service 層 orchestrator `run_keyword_search(db, show_id, raw_query, offset_t1, offset_t2, limit, settings)`（對應 Requirements「T3 OR fallback section」的「僅在 T1+T2=0 時觸發」契約與「T2 collapse threshold」flag 計算，亦對應「T2 collapse threshold」design 決策），行為：依序呼叫 parse → t1 → t2 → 條件呼叫 t3，讀 admin setting 套用 `t2.collapsed` flag，回 response dict。驗證：unit test (a) t1=3,t2=0 → t3 為 None 且 query_t3 未被呼叫（用 mock spy）、(b) t1=0,t2=0 → t3 被呼叫。

## 3. Backend: Endpoint 與 schema（新 endpoint 而非延伸既有 `/search`）

實作 spec Requirements「Keyword search endpoint with strict AND semantics」、「Pagination contract」。

- [x] 3.1 在 `backend/app/schemas/keyword_search.py` 新增 `KeywordSearchRequest`、`KeywordSearchResponse`、`T1Section`、`T2Section`、`T3Section`、`T1Hit`、`T2Hit`、`T3Hit`、`PoolCounts` Pydantic models（對應 Requirement「Pagination contract」的 offset/limit 欄位與 Requirement「Keyword search endpoint with strict AND semantics」的 response 形狀），欄位對齊 design.md「Response Schema」。驗證：`python -c "from app.schemas.keyword_search import KeywordSearchResponse; KeywordSearchResponse.model_json_schema()"` 不報錯且包含 `collapsed` 在 T2Section 而非 T1Section。

- [x] 3.2 在 `backend/app/api/keyword_search.py` 新增 router 與 `POST /shows/{show_id}/keyword-search` handler（對應 Requirement「Keyword search endpoint with strict AND semantics」與「新 endpoint 而非延伸既有 `/search`」design 決策），行為：驗 show 存在（404 `SHOW_NOT_FOUND`）、parse query（空→422 `EMPTY_QUERY`）、呼叫 `run_keyword_search`、回 200。驗證：FastAPI test client 對 (a) 不存在 show → 404、(b) `query="！！！"` → 422、(c) 正常 query → 200 且 response 通過 schema validation。

- [x] 3.3 在 `backend/app/main.py` `include_router` 掛上新 `keyword_search.router`。驗證：`pytest backend/tests/test_keyword_search_endpoint.py::test_route_registered` assert `/shows/{show_id}/keyword-search` 出現在 `app.routes`。

- [x] 3.4 在 endpoint handler 與 service 一同實作「Pagination contract」Requirement：handler 接 `offset_t1`、`offset_t2`（≥0）、`limit`（1..100），service 對 t1/t2 各回 `(items[offset:offset+limit], min(actual_total,100))`。驗證：integration test 對 12 hits 用 (offset=0,limit=5)、(5,5)、(10,5) 依序回 5/5/2 items，三次 `t1.total` 皆為 12。

## 4. Backend: Admin setting（T2 collapse threshold）

實作 spec Requirement「Admin setting keyword_t2_collapse_threshold」與 design「T2 collapse threshold」決策。

- [x] 4.1 新增 `keyword_t2_collapse_threshold`（int，預設 10）到結構化 `app_settings` 表（**非 key-value**，2026-05-31 ingest 校正）：(a) `backend/app/models/app_settings.py` 的 `AppSettings` 加 `keyword_t2_collapse_threshold: Mapped[int]`（`nullable=False, default=10`）；(b) `backend/app/schemas/settings.py` 的 `AppSettingsOut` 加 `keyword_t2_collapse_threshold: int`、`AppSettingsUpdate` 加 `keyword_t2_collapse_threshold: int | None = Field(default=None, ge=1)`；(c) 一支單欄位 alembic migration `ALTER TABLE app_settings ADD COLUMN keyword_t2_collapse_threshold INT NOT NULL DEFAULT 10`；既有 `GET`/`PUT /admin/settings`（`backend/app/api/settings.py`）自動涵蓋新欄位，無需新 route（對應 Requirement「Admin setting keyword_t2_collapse_threshold」與 design「T2 collapse threshold」）。驗證：(1) `alembic upgrade head` 後 `\d app_settings` 含新欄位、`alembic downgrade -1` 可回退；(2) integration test 依序 GET → 10、PUT 為 3、GET → 3、後續 keyword-search 對 t1.total=5 回 `t2.collapsed=true`。

## 5. Backend: 效能與錯誤處理

支援 spec Requirements「T1 same-chunk AND section」與「T2 cross-pool episode AND section」的 100 硬上限子句。

- [x] 5.1 在 `run_keyword_search` 包 DB query 在 `asyncio.wait_for(..., timeout=5.0)`，超時轉 503 `KEYWORD_SEARCH_TIMEOUT`。驗證：unit test 用 mock 強制 sleep 6s，assert 回 503 + 對應 error code。

- [x] 5.2 將 `t1` / `t2` 結果硬上限 100（service 層做 `min(total,100)` 與 slice 邏輯；對應 Requirements「T1 same-chunk AND section」與「T2 cross-pool episode AND section」的 100 cap 子句）。驗證：integration test 種 250 chunks，`offset_t1=95, limit=25` → 回 5 items、`t1.total=100`。

## 6. Frontend: KeywordResults 元件骨架（兩色高亮分配規則）

實作 spec Requirements「Index tab renders sectioned T1 / T2 / T3 layout」、「Two-color highlight for matched terms」。

- [x] 6.1 新增 `src/KeywordResults.jsx`，匯出 `<KeywordResults result terms onMoreT1 onMoreT2 onJumpTo lang />`，按 design「前端 sectioned 渲染元件結構」rendering T1/T2/T3 三 section + 底部 `<BottomModeSwitcher>`（對應 Requirement「Index tab renders sectioned T1 / T2 / T3 layout」）。在 `Object.assign(window, {...})` 末尾匯出。驗證：將 `<KeywordResults>` 以 mock response 接入 `PodcastRAG.html`，瀏覽器開啟 index tab 能看見三段標題與正確 count，且 T3 在 mock t1/t2 皆 0 時才出現。

- [x] 6.2 在同檔 export `highlightTerms(text, terms)` helper（對應 Requirement「Two-color highlight for matched terms」與 design「兩色高亮分配規則」決策），行為：對每個 term 以 `terms.indexOf(term) % 2` 決定橘 `#f97316`（實線下劃線）或青 `#06b6d4`（虛線下劃線），回 React fragment array，包以 `<mark style={{...}}>`。驗證：在 `PodcastRAG.html` 旁開一個臨時 demo 區用 `terms=["A","B","C"]` 確認 A/C 橘實線、B 青虛線；瀏覽器 devtools 檢查 `<mark>` style 屬性。

## 7. Frontend: T1 / T2 / T3 卡片元件

實作 spec Requirements「T1 chunk card shows hit context and expand control」、「T2 episode card pool distribution and inline expand」、「T2 collapsed presentation when threshold exceeded」、「T3 fallback section UI」。

- [x] 7.1 在 `src/KeywordResults.jsx` 內加 `<T1ChunkCard>`（對應 Requirement「T1 chunk card shows hit context and expand control」），行為：預設只顯示命中句前後一句（共 3 句）、有「上下 5 段」inline 展開 btn、有「跳播」btn 透過 `onJumpTo(hit)` callback 觸發既有 sticky audio player **`audio.playFromTime(episode_id, start_time, { audio_url })`**（API 簽名見 `QueryPage.jsx:462`，非泛用 seek）。驗證：瀏覽器手動 — 對 prod 一筆已知 hit chunk 確認預設 3 句、展開後多 5 chunks、跳播 btn 觸發既有 audio player（Change 1 已提供）播放至 `start_time`。

- [x] 7.2 加 `<T2EpisodeCard>`（對應 Requirement「T2 episode card pool distribution and inline expand」；collapsed=false 時使用），行為：顯示 `pool_counts` 三池分計數 + inline「展開查看各段」btn，展開後在卡片下方列出該集匹配 chunks。驗證：手動 — 對 prod fixture 確認三池數字正確、展開後 chunks 出現於同一卡片內、不導航離頁。

- [x] 7.3 加 `<T2CollapsedChip>`（對應 Requirement「T2 collapsed presentation when threshold exceeded」；collapsed=true 時使用），行為：渲染單一 chip「+{total} 集亦有命中」，點擊後 inline 展開為 `<T2EpisodeCard>` 列表（不打 API，用已收到的 `t2.items`）。驗證：admin 將 threshold 設 3、查詢 hit t1.total=5、瀏覽器確認顯示 chip，點擊後展開為完整列表。

- [x] 7.4 加 `<T3FallbackSection>`（對應 Requirement「T3 fallback section UI」），行為：渲染縮小版 chunk cards、prominent mode switcher chip、warning 文案「段內全部命中與全集命中皆無，以下為任一關鍵字的鬆散結果」。驗證：手動 — 對 prod 故意查詢 hit T1+T2=0 的詞，確認 T3 區塊渲染、warning 文案存在、switcher chip 可點。

## 8. Frontend: Pagination 與 Empty state

實作 spec Requirements「Incremental pagination per section」、「Bottom mode switcher chip always visible」、「Zero-result empty state with examples」。

- [x] 8.1 在 `<KeywordResults>` 為 T1 與 T2 各加「顯示更多 5 段／集」btn（對應 Requirement「Incremental pagination per section」），行為：點擊時呼叫 `onMoreT1` / `onMoreT2` callback（由 QueryPage 提供）並 merge 結果；累積到 100 或等於 `total` 時 btn 隱藏。驗證：手動 — 對 `t1.total=40` 的查詢連點 3 次「顯示更多 5 段」（每次 offset+=5），確認 25+5+5+5=40 後 btn 消失。

- [x] 8.2 加 `<BottomModeSwitcher onSwitchMode>`（對應 Requirement「Bottom mode switcher chip always visible」），行為：於 results、loading-with-data、zero-result 三狀態下都渲染於頁尾；點擊 chip 呼叫 `onSwitchMode('semantic' | 'chat')`，由 `QueryPage` wire 到既有 `setActiveTab`（`QueryPage.jsx:231`）。query 字串由既有跨 tab 共用 state `queryText`（`QueryPage.jsx:233`）自動保留，switcher 不自行搬運（2026-05-31 ingest 校正）。驗證：手動 — 三狀態各驗一次 chip 出現，且切到 semantic tab 後輸入框已預填原 query。

- [x] 8.3 加 `<EmptyState>`（對應 Requirement「Zero-result empty state with examples」），行為：當 `t1.total + t2.total + (t3?.total ?? 0) === 0` 時顯示 mode switcher chip + 3 個範例查詢按鈕。範例打 `GET /shows/{show_id}/trending-queries`（已上線於 `events.py:102`，2026-05-31 ingest 確認）；空回應或非 200 時 fallback 寫死 3 筆。驗證：手動 — 對 prod 查詢顯然無結果字串（如 `xyzzzz123`）確認 EmptyState 出現 3 範例 chip + switcher。

## 9. Frontend: QueryPage 接線

實作 spec Requirement「Index tab renders sectioned T1 / T2 / T3 layout」於 QueryPage 索引 tab 的接線部分。

- [x] 9.1 在 `src/QueryPage.jsx` 索引 tab 接線（對應 Requirement「Index tab renders sectioned T1 / T2 / T3 layout」）：**目前索引 tab 是「即將推出」placeholder（disabled 輸入框 `QueryPage.jsx:490` + 空狀態 `:555`），改為**：使用者送出後 POST `/shows/{show_id}/keyword-search`，state 存 response，render `<KeywordResults>` 並提供 `onMoreT1` / `onMoreT2`（用當前 offset+5 重打並 merge）、`onJumpTo`（呼叫既有 `audio.playFromTime(episode_id, start_time, { audio_url })`）與 `onSwitchMode`（wire 到既有 `setActiveTab`）。驗證：手動 — 整段 e2e 在 prod 跑「世運 滅火器」「歌單」「馬世芳」三組查詢，三組各 section 渲染、高亮、pagination、switcher 全部行為對齊上述 spec。

- [x] 9.2 在 QueryPage 索引 tab 加 loading / error UI：fetching 時顯示 spinner、422 顯示「請輸入有效關鍵字」、503 顯示「搜尋逾時，請縮短關鍵字」、500 顯示通用錯誤。驗證：手動 — devtools network throttle 強製造 timeout、改 query 為純標點，逐一確認三種錯誤訊息對應正確。

## 10. 收尾

- [x] 10.1 在 backend 新增 fixture seed script `backend/tests/fixtures/keyword_search_seed.py`，建一 show + 3 episodes 涵蓋 T1/T2/T3 三情境，供 manual prod 驗證重複使用。驗證：`python -m backend.tests.fixtures.keyword_search_seed --dry-run` 列出將建的 row count 與 episode titles，不真寫 DB。

- [x] 10.2 跑 `spectra validate keyword-index-mode` 與本 change 範圍的 pytest 全集，並對 prod 三組查詢做手動 smoke。驗證：(a) `spectra validate` exit 0、(b) `pytest backend/tests/test_keyword_search*.py -q` 全綠、(c) 手動 smoke 三組查詢截圖貼進 PR description。
