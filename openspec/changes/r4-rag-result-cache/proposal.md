## Why

Demo、引導案例（example-prompts chips）、trending 熱門問句、eval 重跑這幾類流量是「逐字重複」的查詢，目前每次都重打 embedding + retrieve_hybrid + enrich（語意模式）或重跑三段 SQL（關鍵字模式），延遲與成本白白重複付出。對話模式 agent 的內部檢索 tool 也反覆呼叫同一組 embedding / retrieve_hybrid。

業界 RAG 系統的 cache 共識是「分層」：exact-match 檢索結果對「逐字重複」流量 ROI 最高且零假命中風險；embedding 快取省掉 OpenAI 呼叫；semantic cache（相似度比對）對自由問句只多補約 20% 命中率、卻帶「200 OK 自信錯答案」的隱形假命中風險（production 實測），需專屬量測才能 ship。

本 change 把快取接縫放在 **service 層**（包住 `rag.retrieve_hybrid` 與 `embed_texts`），讓語意 `/search`、關鍵字 `/keyword-search`、對話 `/query` agent 內部檢索 tool **三條路徑共用同一份檢索 / embedding 快取**。對話模式因此吃得到 embedding + 檢索（+ prefilter tool 輸出含 rerank）三層快取；唯一不快取的是對話模式「LLM 生成的最終答話」——那層非確定性且帶多輪 session state，假命中殺傷力最大，刻意排除。Semantic cache 以 flag-off 的 machinery 形式一併寫入但不啟用，其 enable gate 需要標註集量測假命中率，依賴尚未完成的 EQ5 golden set。

## What Changes

- 新增 `rag_cache` service：Redis（沿用 settings_cache 的 `redis.from_url(celery_broker_url)` 單例）存放 embedding 與檢索結果，封裝 key 組裝、版本綁定、序列化、fail-open（任何 Redis 例外都退回原路徑，永不讓 cache 弄壞查詢）。
- **檢索結果快取（service 層）**：`rag.retrieve_hybrid` 命中時直接回快取 ChunkHit 清單，未命中才查 DB 並回填。三模式共用（語意 `/search`、關鍵字另走 SQL 結果快取、對話 agent 四個檢索 tool）。
  - key = `show_id + hash(question_text + query_embedding) + k + sorted(episode_id_filter) + metadata_filters + corpus_version + retrieval_config_version`。
- **Embedding 快取（service 層）**：`embed_texts` 對單一查詢字串命中時跳過 OpenAI 呼叫。key = `hash(normalize(text)) + embedding_model`。語意 `/search` 與 agent tool 共用。
- **關鍵字結果快取**：`/keyword-search` 命中時回快取的 T1/T2/T3 結果。key = `mode=keyword + show_id + normalize(question) + collapse_threshold + corpus_version`。
- **Rerank**：`search_with_topic_prefilter` tool 的最終輸出（已含 voyage rerank 結果）整包進檢索快取，不另立 rerank 層。
- **cache_hit 揭露**：語意 `/search` 與關鍵字 `/keyword-search` response 新增 `cache_hit` 布林欄位；對話模式的 per-tool cache_hit 走既有 admin debug_trace gate（普通 user 不回）。
- **失效**：新增 per-show `corpus_version`（Redis 計數器 `rag:corpus_ver:{show_id}`），由 transcribe 完成與 ASR 同音字回填套用時 bump；`retrieval_config_version` 在請求時由影響檢索的設定（enable_hyde_retrieval / RRF 權重 / topic routing nudge / two-layer routing / embedding model / rerank flag）雜湊計算。版本變動 → 舊 key 自然 miss，無需主動刪。所有 cache entry 另設保底 TTL。
- **P1.5 預熱**：admin 觸發的 example-prompts backfill 與 trending 問句，於產生後對語意 / 關鍵字模式跑一次查詢灌入 cache。
- **P2 semantic cache machinery（flag off）**：`enable_semantic_cache` 設定預設 False。僅語意模式適用：檢索 cache miss 後，以問句向量在近鄰中找相似度 ≥ 門檻（預設 0.95）的前一筆結果；附問句品質過濾（過短 / 純標點 / 空白擋下不查不存）；命中時記錄 `cache_similarity` 供稽核。本 change 不 flip on，不執行 A/B。

## Non-Goals

- 不快取對話模式 `/query`（agentic）的 LLM 生成最終答話（多輪 session state + 假命中殺傷力過大）。本輪僅讓對話模式吃到 service 層的檢索 / embedding 快取。
- 不在本 change 啟用 semantic cache（P2 flag 維持 off）；不執行 P2 的 A/B 量測與 flip-on 決策。
- 不對關鍵字模式做 semantic cache（索引模式契約是字面 AND match，語意近鄰違反使用者預期）。
- 不另立獨立 rerank 輸出快取層（已被 prefilter tool 最終輸出快取含括）。
- 不做 LRU/LFU 自訂淘汰策略，沿用 Redis TTL + 版本失效即可。

## Capabilities

### New Capabilities

- `rag-result-cache`: RAG 檢索結果分層快取——service 層 exact-match（retrieve_hybrid + embed_texts，三模式共用）+ 關鍵字結果快取 + flag-gated semantic cache machinery + 版本式失效 + 預熱。

### Modified Capabilities

- `rag-query`: 語意 `/search` response 新增 `cache_hit` 欄位；檢索改先查 service 層 cache。
- `keyword-search-mode`: 關鍵字 `/keyword-search` response 新增 `cache_hit` 欄位；查詢前先查結果 cache。

## Impact

- Affected specs: `rag-result-cache`（新）、`rag-query`、`keyword-search-mode`
- Affected code:
  - New:
    - backend/app/services/rag_cache.py
    - backend/tests/test_rag_cache.py
  - Modified:
    - backend/app/services/rag_retrieval.py
    - backend/app/services/embedding.py
    - backend/app/api/query.py
    - backend/app/api/keyword_search.py
    - backend/app/schemas/query.py
    - backend/app/schemas/keyword_search.py
    - backend/app/core/config.py
    - backend/app/workers/tasks.py
    - backend/app/services/asr_homophone.py
    - backend/app/services/example_prompts.py
    - backend/app/workers/example_prompts_task.py
  - Removed: (none)
