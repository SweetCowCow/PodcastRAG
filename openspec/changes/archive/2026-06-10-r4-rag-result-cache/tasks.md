## 1. rag_cache service 與設定基座

- [x] 1.1 在 backend/app/core/config.py 新增設定 `rag_cache_enabled`(預設 True)、`rag_cache_ttl_seconds`(預設 604800)、`enable_semantic_cache`(預設 False)、`semantic_cache_threshold`(預設 0.95)；驗證：import settings 後四欄位有正確預設值（test_rag_cache 內斷言）。
- [x] 1.2 建立 backend/app/services/rag_cache.py，沿用 settings_cache 的 `redis.from_url(settings.celery_broker_url)` lru_cache 單例，提供 get/set_embedding、get/set_retrieval、get/set_keyword、bump_corpus_version、compute_config_version、semantic_lookup；所有 getter miss 回 None。實作「Service-layer retrieval and embedding cache」需求的快取基礎。驗證：backend/tests/test_rag_cache.py round-trip（set 後 get 回同值）+ miss 回 None。
- [x] 1.3 實作「Fail-open behavior」需求（設計 D5：fail-open）：rag_cache 內所有 Redis / 序列化例外 catch + log + 回 None（getter）或 no-op（setter），且 `rag_cache_enabled=False` 時 getter 一律 miss。驗證：test_rag_cache mock Redis 拋例外，getter 回 None、setter 不拋、查詢不中斷。

## 2. Key 組裝與版本失效

- [x] 2.1 實作「Cache key composition」需求（設計 D3：cache key schema）：normalize(text)(trim + 連續空白收斂 + NFKC)與三類 key 組裝（emb / ret / kw），retrieval key 含 question+embedding+k+sorted(episode_id_filter)+metadata_filters+corpus_ver+config_ver。驗證：test_rag_cache 斷言 top_k 不同→key 不同、空白變體→emb key 相同。
- [x] 2.2 實作 compute_config_version（設計 D4：版本式失效）：對 enable_hyde_retrieval、RRF_WEIGHTS、enable_topic_routing_nudge、two-layer routing flag、embedding model、rerank flag 取 sha256。驗證：test_rag_cache 改任一輸入→config_ver 改變。
- [x] 2.3 實作「Version-based invalidation」需求 corpus_version 計數器（Redis key `rag:corpus_ver:{show_id}`，缺值視為 0），在 backend/app/workers/tasks.py transcribe 完成（status→completed）與 backend/app/services/asr_homophone.py 套用既有集數處 INCR。驗證：單元測試斷言 bump 後該 show ret/kw key prefix 改變 + 程式碼 review 確認兩個 bump 點都接上。

## 3. service 層接入（三模式共用）

- [x] 3.1 實作「Service-layer retrieval and embedding cache」需求的 embedding 接入（設計 D1：接縫放 service 層，不放 endpoint 層）：backend/app/services/embedding.py 的 embed_texts 單一查詢字串路徑先查快取、miss 才呼叫 provider、算完回填。驗證：test 以 mock provider 確認第二次相同字串不再呼叫 provider。
- [x] 3.2 retrieve_hybrid 接入檢索快取（設計 D1：接縫放 service 層，不放 endpoint 層；D2：三模式 × cache 層 矩陣（落地真相））：backend/app/services/rag_retrieval.py 的 retrieve_hybrid 先查（含完整 key）、miss 才查 DB、回填序列化 ChunkHit；對話 agent tool 因共用此函式自動受惠。驗證：test round-trip + 版本變動後 miss；程式碼 review 確認 tools.py 路徑未繞過。
- [x] 3.3 關鍵字模式接入結果快取，落實「Keyword search consults the result cache and reports cache_hit」需求：backend/app/api/keyword_search.py 查詢前先查、miss 才跑三段 SQL、回填 T1/T2/T3。驗證：本地整合測試確認二次查 cache_hit、collapse_threshold 改變→miss。

## 4. cache_hit 揭露

- [x] 4.1 落實「cache_hit surfacing」需求與「Semantic search consults the result cache and reports cache_hit」需求：PublicSearchResponse(backend/app/schemas/query.py)與關鍵字 response(backend/app/schemas/keyword_search.py)新增 `cache_hit: bool`，並在 query.py 語意 endpoint 與 keyword_search.py 回填正確值。驗證：本地打兩次相同查詢，第二次 response cache_hit=true。
- [x] 4.2 對話模式 per-tool cache_hit 僅在既有 `?debug_trace=true` admin gate 下回傳（「cache_hit surfacing」需求 admin 部分），非 admin 省略。驗證：admin 帶 debug_trace 看得到 per-tool cache 資訊、非 admin 不含該欄位。

## 5. 預熱

- [x] 5.1 落實「Cache prewarming for guided examples」需求：在 example-prompts 產生流程(backend/app/services/example_prompts.py 與 backend/app/workers/example_prompts_task.py)與 trending 問句後，對語意/關鍵字模式跑一次查詢灌入 cache。驗證：backfill 後首次點該 example chip 之查詢 cache_hit=true（本地 smoke）。

## 6. semantic cache machinery（flag off）

- [x] 6.1 落實「Semantic cache is flag-gated and disabled by default」需求（設計 D6：P2 semantic cache 為 flag-gated machinery，本輪不啟用）：rag_cache.semantic_lookup 僅語意模式，flag on 時 exact miss 後以問句向量找 cosine≥threshold 的前一筆並記 cache_similarity；含問句品質過濾（過短/純標點/空白不查不存）；flag off 直接回 None 零開銷。驗證：test_rag_cache 在 flag off 時 lookup 回 None、flag on + 低品質 query 不查不存。

## 7. prod 驗證

- [x] 7.1 部署後 prod smoke 驗證「Version-based invalidation」與「cache_hit surfacing」需求端到端：同一 show 相同語意查詢二次→cache_hit 由 false→true 且延遲下降；改一個 RRF 權重後相同查詢→cache_hit=false；對某 show bump corpus_ver（重轉或 ASR 回填）後該 show miss、別 show 不受影響；Redis fail-open 不致查詢失敗（手動驗證並記錄結果）。
