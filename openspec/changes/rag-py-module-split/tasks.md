## 1. 抽出 rag_types 模組

- [x] 1.1 建立 `backend/app/services/rag_types.py`，把 `ChunkHit` 與 `MetadataFilters` 從 rag.py 搬入，定義 `__all__ = ["ChunkHit", "MetadataFilters"]`；`rag_types` 不得 import 任何其他 rag 子模組
- [x] 1.2 rag.py 改為 `from app.services.rag_types import *`（或具名 re-export），移除原 class 定義
- [x] 1.3 驗收：`cd backend && python -m pytest tests/ -q` 全綠；`python -c "from app.services import rag; rag.ChunkHit; rag.MetadataFilters"` 無 error

## 2. 抽出 rag_config 模組

- [x] 2.1 建立 `backend/app/services/rag_config.py`，搬入 `_parse_runtime_description_cap`、`_parse_runtime_show_name_filter`、`_parse_use_embedding_v2`、`_resolve_embed_placeholders`、公開常數（`RETRIEVAL_TOP_K`、`RRF_K`、`RRF_PER_SIDE`、`DESCRIPTION_CAP`、`ROUTE_EPISODES_K`、`HISTORY_WINDOW`、`RRF_WEIGHTS`、`TITLE_RRF_PER_SIDE`）與 runtime 快取變數；定義 `__all__`
- [x] 2.2 rag.py re-export rag_config 的公開符號；確認 `RRF_WEIGHTS` 在 rag_config 定義一次、各處以 `from app.services.rag_config import RRF_WEIGHTS` 共用同一 dict 物件，無任何 rebind
- [x] 2.3 更新 `backend/tests/test_rag_retrieval_flags.py` 與 `backend/tests/test_rag_embedding_v2_flag.py`：`_reload_rag` 改為 `importlib.reload(app.services.rag_config)`，斷言對象指向 rag_config 的解析結果
- [x] 2.4 驗收：全 `tests/` 綠，特別是兩個 reload 型 env 測試與 `tests/test_rag_rrf.py`（常數斷言）綠

## 3. 抽出 rag_sql 模組

- [x] 3.1 建立 `backend/app/services/rag_sql.py`，搬入 `_build_ts_query`、`_vector_literal`、`_validate_query_dim`、`_episode_filter_clause`、`_metadata_filter_clause` 與 SQL 模板字串（transcript/description/title 的 RRF 與 semantic-only SQL）；`rag_sql` 依賴 `rag_types`、`rag_config`，保留 `from app.services import tokenizer`
- [x] 3.2 rag.py re-export rag_sql 公開符號（含 `_build_ts_query` 供測試直接呼叫）
- [x] 3.3 更新 tokenizer patch 測試（`backend/tests/test_tokenizer_show_name_filter.py`、`backend/tests/test_rag_rrf.py`、`backend/tests/test_rag_retrieval_flags.py` 中對 `rag.tokenizer` 的 patch）：改為直接 `monkeypatch.setattr` 來源 `app.services.tokenizer.get_show_name_terms`
- [x] 3.4 驗收：全 `tests/` 綠，特別是 `_build_ts_query` 的 show-name 過濾與標點過濾測試綠

## 4. 抽出 rag_enrich 模組

- [x] 4.1 建立 `backend/app/services/rag_enrich.py`，搬入 `enrich_hits`、`_fetch_context_segments`、`_fetch_highlight`、`_fetch_ai_summary_excerpt`、`_fetch_ai_summary_pair`、`_truncate_ai_summary`、`_strip_non_mark_tags`；其中 `_fetch_highlight` 對 `_build_ts_query` 的呼叫改為 `from app.services import rag_sql` 後用 `rag_sql._build_ts_query`
- [x] 4.2 rag.py re-export rag_enrich 公開符號
- [x] 4.3 驗收：全 `tests/` 綠；highlight 相關行為不變

## 5. 抽出 rag_generation 模組

- [x] 5.1 建立 `backend/app/services/rag_generation.py`，搬入 `answer_with_chunks`、`rewrite_question`、`format_enumeration_block`、`_chat_with_tracker`、`_hit_key`、`strip_citations`、`_extract_answer_from_malformed_json`、`_unwrap_self_referential_json`、`REWRITE_SYSTEM_PROMPT`、`ENUMERATION_BLOCK_MAX_LIST_ROWS`
- [x] 5.2 確認 `_chat_with_tracker` 的 OpenAI client 取得與 langfuse / api_health 記錄邏輯原封搬移，初始化時機不變
- [x] 5.3 rag.py re-export rag_generation 公開符號
- [x] 5.4 驗收：全 `tests/` 綠，特別是 `tests/test_strip_citations.py`、`tests/test_answer_unwrap.py`、`tests/test_answer_malformed_json_salvage.py`、`tests/test_chat_enum_grounding.py` 綠

## 6. 抽出 rag_retrieval 模組

- [x] 6.1 建立 `backend/app/services/rag_retrieval.py`，搬入 `retrieve`、`retrieve_descriptions`、`retrieve_titles`、`_should_skip_routing`、`route_episodes`、`retrieve_hybrid`；依賴 `rag_types`、`rag_config`、`rag_sql`
- [x] 6.2 rag.py re-export rag_retrieval 公開符號
- [x] 6.3 驗收：全 `tests/` 綠，特別是 `tests/test_description_retrieval_prefer_v2.py`、`tests/test_chunking_version_coexistence.py`、`tests/test_rag_multi_column_bm25.py` 與 chat agent retrieval 相關測試綠

## 7. rag.py 收斂為純 facade

- [x] 7.1 確認 rag.py 只剩 re-export（`from app.services.rag_xxx import *` 或具名）+ facade 層級 `__all__`，無任何業務邏輯殘留
- [x] 7.2 全域 grep `rag.` 屬性存取點（`app/api/query.py`、`app/services/chat_agent/tools.py`、`app/api/admin/rrf_sweep.py`）逐一確認仍解析成功，無 importer 需修改
- [x] 7.3 驗收：全 `tests/` 綠

## 8. 不變式與行為驗證

- [x] 8.1 驗證 RRF_WEIGHTS 單一物件不變式：`tests/test_admin_rrf_sweep.py` 綠（sweep 後 in-place restore 可見性正確）
- [ ] 8.2 prod chat query smoke：對 prod 用同一問題發查詢，回傳 200 且 citations 數與重構前一致（依 [[reference_prod_eval_session]] 流程，playwright-state cookie + 先 curl /me 驗 200）
- [x] 8.3 確認 `git diff` 僅含模組搬移 + facade + 測試 patch target 變更，無任何行為/參數/SQL/prompt 改動

## 9. 追溯對應（spec 需求 ↔ design 決策 ↔ tasks）

- [x] 9.1 design 決策「D1：採 facade re-export（路線 A），否決徹底清空（B）與保守半拆」由 §1–§7（六個子模組抽出 + rag.py 收斂為 facade）滿足，並同時滿足 spec 需求「RAG service is organized into single-responsibility modules」與「rag.py is a facade that preserves the external interface」
- [x] 9.2 design 決策「D2：`ChunkHit` + `MetadataFilters` 獨立成 `rag_types`（最底層）」由 §1.1 滿足，並同時滿足 spec 需求「Module dependency direction is acyclic」
- [x] 9.3 design 決策「D3：`_build_ts_query` 進 `rag_sql`，retrieval 與 enrich 都向下依賴它」由 §3.1 與 §4.1 滿足
- [x] 9.4 design 決策「D4：測試 patch 策略改為「patch 來源模組」」由 §2.3（reload `rag_config`）與 §3.3（patch 來源 `tokenizer.get_show_name_terms`）滿足
- [x] 9.5 design 決策「D5：`RRF_WEIGHTS` 必須是單一 dict 物件」由 §2.2 與 §8.1 滿足，並同時滿足 spec 需求「RRF_WEIGHTS remains a single mutable object」
