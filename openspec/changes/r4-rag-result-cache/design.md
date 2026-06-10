## Context

PodcastRAG 有三個查詢入口、成本結構不同：
- 語意 `/shows/{id}/search`（query.py:149）：`embed_texts` → `rag.retrieve_hybrid` → `enrich_hits`，無 LLM 生成，輸出即檢索結果。
- 關鍵字 `/shows/{id}/keyword-search`（keyword_search.py:40）：純三段式 AND/OR SQL，無 embedding、無 LLM。
- 對話 `/shows/{id}/query`（query.py:386，agentic）：LLM tool loop；其檢索 tool（`search_within_episode` / `search_across_episodes` / `search_in_episodes` / `search_with_topic_prefilter`，tools.py:342/355/369/398）全部呼叫同一組 `rag.retrieve_hybrid` + `embed_texts`（tools.py:316）；`search_with_topic_prefilter` 額外做 voyage rerank（tools.py:411）。

目前沒有任何查詢結果快取。Redis 已存在（Celery broker），既有 `settings_cache.py` 示範了 `redis.from_url(settings.celery_broker_url)` 的 `lru_cache` 單例 + fail-open 模式。codebase **沒有 corpus_version 欄位**（transcript 僅 `updated_at`），需新建。

業界 RAG cache 共識（見 proposal 引用）：分層；exact-match 對逐字重複流量 ROI 最高且零假命中；semantic cache 真實 hit rate 約 20% 且假命中是隱形 200-OK 錯答案，需專屬量測才能 ship。

## Goals / Non-Goals

**Goals:**

- 把快取接縫放在 service 層（`retrieve_hybrid` + `embed_texts`），讓三模式共用一份檢索 / embedding 快取。
- 語意與關鍵字模式回傳 `cache_hit`；對話模式 per-tool cache_hit 走 admin debug_trace。
- 版本式失效：語料變更（transcribe / ASR 回填）或檢索設定變更（HyDE / RRF 權重 / routing flag / model）後，舊 cache 自動 miss，不回髒資料。
- example-prompts / trending 預熱，demo 與引導案例冷啟動即命中。
- 寫入 semantic cache machinery（flag off），但不啟用。

**Non-Goals:**

- 不快取對話模式 LLM 生成的最終答話。
- 不啟用 semantic cache、不跑 P2 A/B（本輪）。
- 不對關鍵字模式做 semantic cache。
- 不另立獨立 rerank 快取層。
- 不做自訂淘汰策略（沿用 TTL + 版本失效）。

## Decisions

### D1：接縫放 service 層，不放 endpoint 層

包住 `rag.retrieve_hybrid` 與 `embed_texts`，三模式（含對話 agent 內部 tool）自動共用。代價是 blast radius 變大（所有檢索過 cache），由版本失效 + fail-open 控住。endpoint 層的 `cache_hit` 是「該 request 的檢索是否全部來自 cache」的彙整旗標。

### D2：三模式 × cache 層 矩陣（落地真相）

| Cache 層 | 語意 `/search` | 關鍵字 `/keyword-search` | 對話 `/query`（agentic）|
|---|---|---|---|
| Embedding（service 層）| ✅ | ➖ 無 embedding | ✅ agent tool 共用 |
| 檢索結果 retrieve_hybrid（service 層）| ✅（=全回應）| ✅ 改快取 SQL 結果 | ✅ agent tool 共用 |
| Rerank 結果 | ➖ 此路徑無 rerank | ➖ | ✅ 含在 prefilter tool 輸出快取 |
| 最終生成答案 | ➖ 無生成 | ➖ 無生成 | ❌ 刻意排除 |
| Semantic cache（P2 flag off）| ✅ 限此模式 | ➖ | ❌ 永不 |
| 預熱 / cache_hit 揭露 | ✅ response 欄位 | ✅ response 欄位 | cache_hit 走 debug_trace |

圖例：✅做 ／ ➖不適用 ／ ❌刻意排除。

### D3：Cache key schema

- **Embedding 層**：`emb:{embedding_model}:{sha256(normalize(text))}` → value = JSON float list。
- **檢索層（retrieve_hybrid）**：`ret:{show_id}:{corpus_ver}:{config_ver}:{sha256(question + ":" + bytes(query_embedding) + ":" + k + ":" + sorted(episode_id_filter) + ":" + metadata_filters)}` → value = 序列化 ChunkHit 清單。key 同時含 question（ts_rank 字面用）與 embedding（向量用），兩者皆影響輸出。
- **關鍵字層**：`kw:{show_id}:{corpus_ver}:{sha256(normalize(question) + ":" + collapse_threshold)}` → value = 序列化 T1/T2/T3 結果。
- `normalize(text)` = trim + 連續空白收斂為單一空白 + NFKC（中文大小寫多為 no-op，但統一全形半形）。

### D4：版本式失效

- **corpus_version**：Redis 計數器 key `rag:corpus_ver:{show_id}`，缺值視為 0。`transcribe_episode` 完成（tasks.py，status→completed）與 ASR 同音字回填「套用到既有集數」時 `INCR`。語料一變，該 show 所有 `ret:` / `kw:` key 因 prefix 帶 corpus_ver 而自然全 miss（不需逐 key 刪）。
- **retrieval_config_version**：請求時即時計算 = `sha256` of（enable_hyde_retrieval, RRF_WEIGHTS, enable_topic_routing_nudge, two-layer routing flag, embedding model 名, rerank flag）。admin 調任一參數 → config_ver 變 → 舊 key miss。
- **保底 TTL**：所有 entry 設 TTL（預設 7 天，`settings.rag_cache_ttl_seconds`），防止版本永不變動時的無限累積。

### D5：fail-open

`rag_cache` 任何 Redis 例外（連線失敗 / 序列化錯）都 catch + log + 退回原檢索路徑。cache 是純加速層，刪掉它功能不壞只是變慢（介面深度檢查的 deletion test）。

### D6：P2 semantic cache 為 flag-gated machinery，本輪不啟用

`settings.enable_semantic_cache` 預設 False。啟用後僅語意模式：檢索 cache miss → 以問句向量在 Redis 存的近鄰中找 cosine ≥ `settings.semantic_cache_threshold`（預設 0.95）的前一筆，命中則回該結果並在 response 記 `cache_similarity`。問句品質過濾：長度 < 門檻字數 / 純標點 / 空白 → 不查不存。**Enable gate（寫在此處，本輪不執行）**：flip on 前須以標註集量到「假命中率 ≤ 5% 且相對 exact-match 有淨命中增益」，量尺依賴 EQ5 golden set。

## Implementation Contract

**Behavior（使用者 / 操作者觀察到的）：**
- 對同一 show 連續送出逐字相同的語意或關鍵字查詢，第二次起 response `cache_hit=true` 且延遲明顯下降。
- 點擊 example-prompts chip（預熱過）首次即 `cache_hit=true`。
- admin 改 RRF 權重 / 開關 HyDE，或某集重新轉錄 / ASR 回填套用後，下一次相同查詢 `cache_hit=false`（版本失效生效），結果反映新設定 / 新語料。
- 對話模式查詢時，agent 內部重複的 tool search 命中 service 層快取（per-tool cache_hit 於 `?debug_trace=true` 可見）；最終答話每次仍由 LLM 生成（不快取）。
- Redis 全掛時所有查詢照常成功，只是無加速（fail-open）。

**Interface / data shape：**
- 新 service `backend/app/services/rag_cache.py`，公開：`get_embedding(text, model)` / `set_embedding(...)`、`get_retrieval(key_parts)` / `set_retrieval(...)`、`get_keyword(...)` / `set_keyword(...)`、`bump_corpus_version(show_id)`、`compute_config_version()`、`semantic_lookup(show_id, vec)`（flag-gated）。所有 getter miss 回 None。
- `embed_texts`（embedding.py）與 `rag.retrieve_hybrid`（rag_retrieval.py）內部先查 cache、miss 才算、算完回填。
- `PublicSearchResponse`（schemas/query.py）與關鍵字 response（schemas/keyword_search.py）新增 `cache_hit: bool`。
- `config.py` 新增：`enable_semantic_cache: bool=False`、`semantic_cache_threshold: float=0.95`、`rag_cache_ttl_seconds: int=604800`、`rag_cache_enabled: bool=True`（exact-match 總開關，可一鍵停 cache）。
- corpus_version bump 點：`backend/app/workers/tasks.py`（transcribe 完成）、`backend/app/services/asr_homophone.py`（回填套用既有集數）。

**Failure modes：**
- Redis 例外 → fail-open（log warning、走原路徑）。
- 序列化 / 反序列化錯 → 視為 miss + log，不拋給 caller。
- semantic cache flag off → `semantic_lookup` 直接回 None，零額外開銷。

**Acceptance criteria：**
- `backend/tests/test_rag_cache.py`：key 組裝確定性、normalize、版本變動使 key 改變、fail-open（mock Redis 拋例外仍回 None / 原值）、TTL 設定、semantic flag off 時 lookup 回 None。
- exact-match round-trip 測試：set 後 get 回同值。
- prod smoke：同句二次查 `cache_hit=true`；改 RRF 權重後 `cache_hit=false`；某 show bump corpus_ver 後該 show miss、別 show 不受影響。

**Scope boundaries：**
- In scope：rag_cache service、retrieve_hybrid / embed_texts / keyword-search cache 接入、cache_hit 欄位、corpus/config 版本、預熱、semantic machinery（off）。
- Out of scope：對話最終答話快取、semantic cache 啟用與 A/B、rerank 獨立層、淘汰策略。

## Risks / Trade-offs

- **Blast radius（D1 的代價）**：所有檢索過 cache，失效邏輯一旦有 bug 全模式可能服務舊結果。緩解：版本綁進 key（不靠主動刪）、fail-open、`rag_cache_enabled` 總開關可一鍵停。
- **corpus_version bump 漏點**：若有改寫 chunk 文字 / embedding 的路徑沒 bump，會殘留舊結果到 TTL。緩解：bump 點集中（transcribe 完成 + ASR 回填）並在 tasks 明列；TTL 7 天保底。
- **對話模式命中率偏低**：agent 動態改寫 query → 內部 tool query 不逐字重複，命中率低於 `/search`。可接受：此好處是共用 cache 免費附帶，非本 change 主要 KPI。
- **embedding 向量入 key 的成本**：對 1536 維 float 取 hash 有 CPU 成本但遠低於一次檢索；且 embedding 本身也快取，重複查不會重算向量。
- **semantic cache 寫了不開**：增加未啟用程式碼。緩解：flag off 零開銷、enable gate 明寫、與 HyDE flag-gated 家規一致。
