## Why

`backend/app/services/rag.py` 已成長到 1330 行、26 個函式 + 3 個 class，混合了五種互不相干的職責（config 解析、SQL 建構、檢索、結果加料、LLM 生成）。這個 god module 造成三個實際痛點：(1) 改 generation 容易誤觸 retrieval（「prompt change 從來不 orthogonal 於 retrieval」的歷史教訓）；(2) eval 歸因困難，diff 落點無法對應變動性質；(3) 即將解凍的 EQ3c BM25 要改的 `_build_ts_query`（280 行）深埋在主檔，改動面被放大。趁現在拆分，後續每次改動都更安全。

## What Changes

純內部重構，**對外行為零改變**。把 rag.py 依職責拆成 6 個子模組，rag.py 保留為 facade（`from rag_xxx import *`）維持所有 `rag.X` 外部介面不變：

- 新增 `rag_types.py`：`ChunkHit`、`MetadataFilters`（三層共用資料結構，獨立以根除循環 import）
- 新增 `rag_config.py`：`_parse_*` 解析函式、module-level 公開常數（`RRF_WEIGHTS`、`RRF_K`、`RETRIEVAL_TOP_K`、`DESCRIPTION_CAP`、`ROUTE_EPISODES_K`、`HISTORY_WINDOW`、`TITLE_RRF_PER_SIDE`）、runtime 快取變數
- 新增 `rag_sql.py`：`_build_ts_query`（EQ3c 標靶）、`_vector_literal`、`_validate_query_dim`、episode/metadata filter clauses、SQL 模板字串
- 新增 `rag_retrieval.py`：`retrieve`、`retrieve_descriptions`、`retrieve_titles`、`route_episodes`、`_should_skip_routing`、`retrieve_hybrid`
- 新增 `rag_enrich.py`：`enrich_hits` 與 `_fetch_*`、`_truncate_ai_summary`、`_strip_non_mark_tags`
- 新增 `rag_generation.py`：`answer_with_chunks`、`rewrite_question`、`format_enumeration_block`、`_chat_with_tracker`、`_hit_key`、`strip_citations` 與 JSON 修復函式
- 修改 `rag.py`：清空實作，改為 re-export facade，維持外部 `rag.X` 介面與 admin 對 `rag.RRF_WEIGHTS` 的執行期 in-place 改寫
- 修改 ~4 個測試檔的 patch/reload target（reload `rag_config`、直接 patch 來源 `app.services.tokenizer.get_show_name_terms`）

## Non-Goals

- **不消滅 rag.py**：刻意保留為 facade，避免 3 個 importer 與 admin sweep 全面改 import（已 discuss 否決「徹底清空 rag.py」的激進路線 B）。
- **不改任何檢索/生成行為**：不調 RRF 權重、不動 prompt、不改 SQL 語意。任何行為變化都屬 bug，不在本 change 範圍。
- **不做 BM25**：EQ3c 是後續獨立 change，本次只把 `_build_ts_query` 隔離出去為它鋪路。
- **不拆 `rag_rerank.py`**：已是獨立模組，不在本次範圍。

## Capabilities

### New Capabilities

- `rag-service-layout`: 規範 RAG service 的模組職責邊界與 facade 契約 — rag.py 作為 re-export facade 維持外部 `rag.X` 介面穩定，六個子模組各司單一職責，依賴方向分層無循環。這是維護性架構不變式，約束未來改動。

### Modified Capabilities

(none) — 既有能力的「行為」契約完全不變，無 spec-level 行為需求變更。本 change 不修改任何現有 spec。

## Impact

- Affected specs: 新增 `rag-service-layout`（架構不變式，非行為變更）
- Affected code:
  - New: `backend/app/services/rag_types.py`、`backend/app/services/rag_config.py`、`backend/app/services/rag_sql.py`、`backend/app/services/rag_retrieval.py`、`backend/app/services/rag_enrich.py`、`backend/app/services/rag_generation.py`
  - Modified: `backend/app/services/rag.py`、`backend/tests/test_rag_retrieval_flags.py`、`backend/tests/test_rag_embedding_v2_flag.py`、`backend/tests/test_tokenizer_show_name_filter.py`、`backend/tests/test_rag_rrf.py`
  - Removed: 無
- 真實 importer（不需改 import，靠 facade）：`backend/app/api/query.py`、`backend/app/services/chat_agent/tools.py`、`backend/app/api/admin/rrf_sweep.py`
