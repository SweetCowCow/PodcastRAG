## 1. Schema + Migration（episodes.guests JSONB column / episodes.title_tsvector generated column）

- [x] 1.1 撰寫 alembic migration `r33_episodes_guests_and_title_tsvector.py` 實作 `episodes.guests JSONB column` + `episodes.title_tsvector generated column`：(a) `episodes.guests` JSONB NOT NULL DEFAULT `'[]'::jsonb`、(b) `idx_episodes_guests` GIN index on `guests jsonb_path_ops`、(c) `episodes.title_tsvector` generated column 公式 `to_tsvector('simple', tokenize_for_tsvector(title))` 使用 R3.1 既有 tokenizer SQL function、(d) `idx_episodes_title_tsv` GIN index
- [x] 1.2 更新 `app/models/episode.py` SQLAlchemy model：加 `guests: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)`、加 `title_tsvector` 為 read-only computed field
- [x] 1.3 寫 `tests/test_episode_guests_schema.py`：驗證 `episodes.guests JSONB column` default `[]`、`@>` 查詢、`episodes.title_tsvector generated column` 對 title UPDATE 自動更新

## 2. RSS Parser Guests 抽取（RSS Title 來賓抽取 / 來賓清單欄位 / RSS feed parser）

實作 Decision 1：guests 雙路徑寫入 + admin UI 編輯。

- [x] 2.1 在 `app/services/rss_parser.py`（屬 `RSS feed parser` 範圍）新增 `GUESTS_REGEX = re.compile(...)` 常數，pattern 涵蓋 `Ft.`/`Feat.`/`feat.`/`featuring`/`【ft.`/`【Ft.`/`【feat.`，flags=IGNORECASE
- [x] 2.2 新增純函數 `extract_guests_from_title(title: str) -> list[str]` 實作 `RSS Title 來賓抽取`：跑 regex.findall，每個 match strip + 切分隔符 (`/`、`、`、`,`、`，`)，去重保持原順序，回 list
- [x] 2.3 修改 `_parse_episode`：呼叫 extract_guests，把結果加入回傳的 `ParsedEpisode.guests` 欄位（落實 `來賓清單欄位` 寫入路徑）
- [x] 2.4 更新 `ParsedEpisode` dataclass + show sync 路徑（`app/api/shows.py` create_show、refresh_episodes 任務），把 guests 寫進 `episodes.guests`
- [x] 2.5 寫 `tests/test_rss_guests_extraction.py`：覆蓋 6 個 case（Ft. / Feat. / 【ft.】 / 多人逗號分隔 / 多人斜線分隔 / 無 pattern→空 list）

## 3. Backfill 既有 Episodes（既有 episode 一次性 backfill）

- [x] 3.1 寫 `scripts/backfill_guests.py` 實作 `既有 episode 一次性 backfill`：支援 `--all` 跑全 episodes、`--show-id <UUID>` 限定單 show、`--dry-run` 不 commit；逐集呼叫 `extract_guests_from_title(episode.title)` 後 UPDATE，每 100 集 print 進度
- [x] 3.2 寫 `tests/test_backfill_guests.py`：以 fixture 建 5 集 mock title、跑 script、verify guests 正確寫入
- [x] 3.3 開發環境 manual smoke：對本機 ~10 集 fixture 跑一次驗 idempotent（兩次跑結果一致）

## 4. Admin Episode Guests 編輯 API（Admin 編輯 Guests）

- [x] 4.1 新增 `app/schemas/episode_guests.py`：`EpisodeGuestsOut` (`episode_id, title, published_at, guests`)、`EpisodeGuestsUpdate` (`guests: list[str]` 每 element 非空且 strip 後 ≤ 100 字元)
- [x] 4.2 新增 `app/api/admin/episode_guests.py` 實作 `Admin 編輯 Guests`：(a) `GET /admin/episodes/{episode_id}/guests`、(b) `PUT /admin/episodes/{episode_id}/guests`（require_admin）、(c) `GET /admin/shows/{show_id}/guests` 列出該 show 全 episodes（按 published_at desc）
- [x] 4.3 在 `app/api/admin/__init__.py` 註冊 router
- [x] 4.4 寫 `tests/test_admin_episode_guests.py`：覆蓋 GET 單集 / PUT 單集 / 非 admin 403 / 不存在 episode 404 / 列出 show guests

## 5. Admin Frontend Guests 編輯 UI（Admin 編輯 Guests — frontend）

實作 Decision 1：guests 雙路徑寫入 + admin UI 編輯（前端側）。

- [x] 5.1 在 `src/AdminPage.jsx` 加新 Tab `"Guests"`，路由值 `admin-guests`
- [x] 5.2 新增 `src/AdminEpisodeGuestsTab.jsx`：(a) 上方 show selector dropdown、(b) 選定 show 後 fetch `/admin/shows/{show_id}/guests`、(c) 列出 episodes（按 published_at desc）、(d) 每集 row 顯示 title + guests chip + 「編輯」button
- [x] 5.3 編輯 modal：textarea（每行一個 guest）+「儲存」呼叫 PUT，成功後更新本地 state + close modal
- [x] 5.4 在 `src/Shared.jsx` 補必要 token / icon（Edit icon）
- [x] 5.5 雙語文案：所有 user-facing 字串提供 zh + en

## 6. LLM Query Entity Extractor 服務（LLM 抽取使用者問句的 Entity / Entity 抽取失敗的 fail-open 行為 / Entity 抽取作為可配置 AI Step / AI step configuration table with hardcoded step keys）

實作 Decision 2：LLM query entity extractor 走獨立 service + admin step。

- [x] 6.1 新增 `app/schemas/query_entity.py` 定義 `QueryEntities` Pydantic model `{date_range: tuple[datetime, datetime] | None, guests: list[str], topics: list[str]}`，含 JSON schema 給 LLM response_format 用（屬 `LLM 抽取使用者問句的 Entity` 介面定義）
- [x] 6.2 新增 `app/services/query_entity.py` 實作 `LLM 抽取使用者問句的 Entity` + `Entity 抽取失敗的 fail-open 行為`：公開 `async def extract_entities(client, model, question: str, now: datetime) -> QueryEntities`；system prompt 含 8 個 few-shot examples（明確日期 / 抽象「去年」/ 抽象「最近這集」/ 來賓名 / 多 entity 混合 / 純抽象問題 / topic 列舉 / 別名）；response_format JSON object + JSON schema validation；retry 1 次後 fail-open 回 empty entities
- [x] 6.3 在 `app/services/ai_step_resolver.py` 加 `entity_extraction` step 支援（落實 `Entity 抽取作為可配置 AI Step`）
- [x] 6.4 寫 `tests/test_query_entity.py`：mock LLM client 覆蓋 8 個 scenario（含 fail-open 三條：APIError / invalid JSON / schema 不符）
- [x] 6.5 alembic migration `r33_add_entity_extraction_step.py`（更新 `AI step configuration table with hardcoded step keys` 加第六個 step）：INSERT `ai_steps` 一筆 step_key='entity_extraction', step_type='chat', model='gpt-4o-mini', base_url=NULL, api_key_id=（auto-detect 唯一 OpenAI key 否則 NULL）；同時調整 CHECK constraint 從 5 → 6 step_key 白名單
- [x] 6.6 admin frontend：`AdminPage.jsx` AI Steps tab 已 generic 處理新 step，verify 顯示 entity_extraction row 可編輯（測 prod 不需改 code）

## 7. Bake-off Entity Extractor Models（Entity 抽取作為可配置 AI Step — model selection）

實作 Decision 2 的 bake-off methodology。

- [x] 7.1 寫 `scripts/bakeoff_entity_extractor.py`：對 R1.2 dataset 48 題各跑三 model（gpt-4o-mini / gemini-2.5-flash-lite / claude-haiku-4-5），輸出 JSONL 含 question + each model 抽出的 entities
- [x] 7.2 人工 audit 抽 10 題對比 model 抽出 entity vs 預期，計算 entity F1（precision / recall on guests + date_range hit/miss）；結果寫 `docs/case-studies/r33-metadata-filter.md` Stage 2 section
- [x] 7.3 結論寫進 case study：選擇最便宜且 entity F1 ≥ 0.7 的 model 作為 prod 預設

## 8. RAG 三池 RRF SQL Refactor（Semantic search endpoint returns ranked chunks / RRF pool weights configurable in Python）

實作 Decision 3：BM25 多欄位走「per-query rank summation」而非 setweight bitmap。

- [x] 8.1 在 `app/services/rag.py` 新增 module-level constant `RRF_WEIGHTS = {"chunk": 1.0, "description": 0.7, "title": 0.5}`（`RRF pool weights configurable in Python`）；semantic pool 永遠 1.0 不在這
- [x] 8.2 改 `_TRANSCRIPT_RRF_SQL` + `_DESC_RRF_SQL` 兩個 CTE 落實 `Semantic search endpoint returns ranked chunks` 變更：在 `combined` 階段把 RRF 分量乘上 weight 參數（傳 `:weight_chunk`, `:weight_desc`, `:weight_title`）
- [x] 8.3 新增 `_TITLE_LEXICAL_SQL`：對 `episodes.title_tsvector @@ to_tsquery(...)` 做 ts_rank ROW_NUMBER，產生 title pool ranks 併入 RRF（補完 `Semantic search endpoint returns ranked chunks` 三池融合）
- [x] 8.4 修改 `retrieve_hybrid` 函式 signature：接受 `metadata_filters: MetadataFilters | None`（含 guests / date_range），把 SQL `WHERE` clause 加上 `episodes.guests @> :guests` / `episodes.published_at BETWEEN :start AND :end`；title pool 一併合併進 final RRF
- [x] 8.5 修改 `retrieve_descriptions` 同步加 metadata_filters 支援
- [x] 8.6 寫 `tests/test_rag_multi_column_bm25.py`：以 fixture seed title-only match / desc-only match / chunk-only match 三集，verify 三池融合 ranking 順序符合 weight 預期

## 9. Chat Endpoint 整合 Entity Extractor + Enumeration（Chat endpoint answers with citations using Tier 2 RAG / Cross-episode enumeration response shape / Entity 抽取整合進 chat path）

實作 Decision 4：cross-episode 列舉題型走「response shape 擴充」而非新 endpoint。

- [x] 9.1 修改 `app/api/query.py` chat path 落實 `Chat endpoint answers with citations using Tier 2 RAG` (modified) 與 `Entity 抽取整合進 chat path`：在 `rewrite` 之後、`route_episodes` 之前 await `query_entity.extract_entities(...)`；entity 結果傳入 `retrieve_hybrid(metadata_filters=...)`
- [x] 9.2 新增 `_compute_enumeration_episodes` 函式落實 `Cross-episode enumeration response shape`：當 entity 非空 OR question regex match `"哪幾集|哪集|哪些集"` → 跑 SQL `SELECT id, title, published_at, guests, ai_summary FROM episodes WHERE show_id=:show_id AND <entity filters>` 回 list；空時回 None
- [x] 9.3 修改 `app/schemas/query.py` `ChatResponse`：加 `enumeration_episodes: list[EpisodeRef] | None = None`；新增 `EpisodeRef` schema
- [x] 9.4 寫 `tests/test_query_chat_metadata_filter.py`：(a) entity 抽出 guest 觸發 filter + enumeration、(b) entity 抽出 date 觸發 filter + enumeration、(c) entity 失敗 fail-open（mock raise 看回 200）、(d) 純 topic 列舉 rule pattern 觸發 enumeration

## 10. 前端 Cross-Episode Enumeration UI（Cross-episode enumeration response shape — frontend）

實作 Decision 4：前端 cross-episode 列舉 UI。

- [x] 10.1 在 `src/QueryPage.jsx` ChatBubble 渲染：當 response 帶 `enumeration_episodes` 非空，顯示「相關集數」section（在 answer 下、citations 上）
- [x] 10.2 每集 row：title + 發佈日期 + guests chip + 60-150 字 ai_summary + 「跳到這集」button（navigate 到 TranscriptPage）
- [x] 10.3 雙語：「相關集數」/「Related Episodes」，「跳到這集」/「Jump to this episode」
- [x] 10.4 verify mobile-friendly（窄螢幕 ai_summary 截斷 + 展開）

## 11. Eval 對照 R3.2 Baseline

實作 Decision 5：Eval 對照範圍。

- [x] 11.1 跑 R1.2 dataset eval：`python -m backend.eval.runners.run --dataset backend/eval/datasets/this-not-that-cool.json --backend-url https://api.podcastrag.app --top-k 5 --metric-level episode --skip-judge`，存進 `backend/eval/runs/r33-baseline/`
- [x] 11.2 對比 R3.2 baseline 數字（從 R3.2 case study 抓），算 absolute pp 差距 + per-category breakdown（fact / comprehension / cross-episode / negative / code-switch）
- [x] 11.3 額外針對 cross-episode 列舉題（從 dataset 挑或新增 5 題）測 `enumeration_episodes` precision / recall

## 12. Case Study + Release Log + Archive

- [x] 12.1 寫 `docs/case-studies/r33-metadata-filter.md`（不入 git per rule）：含 4 section（schema decisions / entity extractor bake-off / RRF weights tuning / final eval）
- [x] 12.2 跑 `gitleaks detect` 確認新 commits 無 secret
- [x] 12.3 commit 全部 R3.3 變動（spectra-commit r3-3-metadata-filter 走流程）
- [x] 12.4 push + verify Zeabur build 綠 + chrome-devtools-mcp prod 驗證 Guests admin tab + 隨機問一個列舉題確認 enumeration_episodes 正確
- [x] 12.5 補 Release Log v1.6 entry（per `feedback_release_log_maintenance.md`）：使用者視角講「現在可以問『馬世芳上過哪幾集』『2024 那集』」
- [x] 12.6 `/spectra-archive r3-3-metadata-filter` + 更新 `docs/roadmap.md` + 同步 memory `project_pending_changes.md`
