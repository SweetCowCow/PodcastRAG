# query-entity-extraction Specification

## Purpose

TBD - created by archiving change 'r3-3-metadata-filter'. Update Purpose after archive.

## Requirements

### Requirement: LLM 抽取使用者問句的 Entity

系統 SHALL 在使用者送出 chat query 時，透過 LLM service 抽取問句內的 metadata entity，包含 date_range / guests / topics 三類，回傳結構化結果供 retrieval 階段使用。

#### Scenario: 抽出明確日期範圍

- **WHEN** 使用者問 `"2024 那集的內容是什麼"`
- **THEN** 系統 MUST 回傳 `date_range = (2024-01-01T00:00:00Z, 2024-12-31T23:59:59Z)`

#### Scenario: 抽出抽象時間敘述

- **WHEN** 使用者問 `"去年那集講過什麼"` 且系統時間為 2026 年
- **THEN** 系統 MUST 回傳 `date_range = (2025-01-01T00:00:00Z, 2025-12-31T23:59:59Z)`

#### Scenario: 抽出來賓名

- **WHEN** 使用者問 `"馬世芳上過哪幾集"`
- **THEN** 系統 MUST 回傳 `guests = ["馬世芳"]`

#### Scenario: 抽出多個 entity 類別

- **WHEN** 使用者問 `"2024 馬世芳那集的料理是什麼"`
- **THEN** 系統 MUST 回傳 `date_range` 包含 2024 + `guests = ["馬世芳"]` + `topics` 含「料理」相關詞

#### Scenario: 沒有可抽 entity

- **WHEN** 使用者問 `"主持人有什麼興趣"`（純抽象問題）
- **THEN** 系統 MUST 回傳 `date_range = None, guests = [], topics = []`


<!-- @trace
source: r3-3-metadata-filter
updated: 2026-05-16
code:
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/eval/datasets/this-not-that-cool.json
  - docs/ai-steps.md
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/embedding.py
  - backend/app/services/rag.py
  - src/AdminTokenizerTab.jsx
  - index.html
  - backend/app/api/admin/__init__.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/tokenizer.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - src/App.jsx
  - backend/app/services/citation_parser.py
  - backend/app/schemas/query.py
  - backend/app/models/ai_step.py
  - src/AdminPage.jsx
  - backend/app/services/query_entity.py
  - backend/app/services/topic_segmentation.py
  - backend/app/models/episode.py
  - src/TranscriptPage.jsx
  - backend/scripts/backfill_guests.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/eval/datasets/_pending_review.json
  - CLAUDE.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/eval/datasets/_schema.json
  - backend/app/workers/topic_task.py
  - src/QueryPage.jsx
  - backend/scripts/backfill_topic_labels.py
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/app/schemas/episode_guests.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/api/shows.py
  - backend/app/api/query.py
  - backend/eval/metrics/recall.py
  - backend/eval/datasets/README.md
  - backend/app/services/rss_parser.py
  - docs/roadmap.md
  - backend/app/services/sync.py
  - backend/eval/scripts/validate_schema.py
  - src/ReleaseLogPage.jsx
  - backend/app/services/description_rechunker.py
  - src/releaseLog.jsx
  - backend/eval/runners/run.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/chunking_status.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/key_resolver.py
  - backend/app/models/transcript_chunk.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/Shared.jsx
  - backend/app/workers/celery_app.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/workers/tasks.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/app/schemas/query_entity.py
  - backend/eval/scripts/build_golden_set.py
tests:
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_topic_segmentation_persist.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_query_entity.py
-->

---
### Requirement: Entity 抽取失敗的 fail-open 行為

系統 SHALL 在 entity 抽取失敗時退回不 filter 的行為，retrieval 仍然繼續執行，使用者不可見錯誤。

#### Scenario: LLM API 連線失敗

- **WHEN** entity_extraction step 對 LLM API 連線失敗（APIConnectionError）
- **THEN** 系統 MUST log warning、回 `QueryEntities(date_range=None, guests=[], topics=[])`、retrieval 繼續走完整路徑、使用者收到正常 chat response

#### Scenario: LLM 回傳 invalid JSON

- **WHEN** LLM response 不是 valid JSON 或缺欄位
- **THEN** 系統 MUST retry 一次；retry 仍失敗 MUST 回 empty entities，不 raise 5xx

#### Scenario: LLM 回傳 schema 不符的值

- **WHEN** LLM 回 `{"date_range": "去年", "guests": "馬世芳"}` （type 不對：date_range 應為 ISO 字串 list、guests 應為 list）
- **THEN** 系統 MUST 視為抽取失敗、回 empty entities


<!-- @trace
source: r3-3-metadata-filter
updated: 2026-05-16
code:
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/eval/datasets/this-not-that-cool.json
  - docs/ai-steps.md
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/embedding.py
  - backend/app/services/rag.py
  - src/AdminTokenizerTab.jsx
  - index.html
  - backend/app/api/admin/__init__.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/tokenizer.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - src/App.jsx
  - backend/app/services/citation_parser.py
  - backend/app/schemas/query.py
  - backend/app/models/ai_step.py
  - src/AdminPage.jsx
  - backend/app/services/query_entity.py
  - backend/app/services/topic_segmentation.py
  - backend/app/models/episode.py
  - src/TranscriptPage.jsx
  - backend/scripts/backfill_guests.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/eval/datasets/_pending_review.json
  - CLAUDE.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/eval/datasets/_schema.json
  - backend/app/workers/topic_task.py
  - src/QueryPage.jsx
  - backend/scripts/backfill_topic_labels.py
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/app/schemas/episode_guests.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/api/shows.py
  - backend/app/api/query.py
  - backend/eval/metrics/recall.py
  - backend/eval/datasets/README.md
  - backend/app/services/rss_parser.py
  - docs/roadmap.md
  - backend/app/services/sync.py
  - backend/eval/scripts/validate_schema.py
  - src/ReleaseLogPage.jsx
  - backend/app/services/description_rechunker.py
  - src/releaseLog.jsx
  - backend/eval/runners/run.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/chunking_status.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/key_resolver.py
  - backend/app/models/transcript_chunk.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/Shared.jsx
  - backend/app/workers/celery_app.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/workers/tasks.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/app/schemas/query_entity.py
  - backend/eval/scripts/build_golden_set.py
tests:
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_topic_segmentation_persist.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_query_entity.py
-->

---
### Requirement: Entity 抽取整合進 chat path

系統 SHALL 在 chat query 處理流程中，於 query rewrite 之後、retrieval 之前呼叫 entity extractor，並將抽出 entity 傳給 retrieval 階段。

#### Scenario: 抽出 entity 後傳給 retrieval

- **WHEN** chat query `"2024 那集"` 經過 entity extraction 抽出 `date_range = (2024-01-01, 2024-12-31)`
- **THEN** retrieval 階段 MUST 對 episodes 表套用 `published_at BETWEEN ... AND ...` hard filter

#### Scenario: 抽出 guests 後傳給 retrieval

- **WHEN** chat query 抽出 `guests = ["馬世芳"]`
- **THEN** retrieval 階段 MUST 對 episodes 表套用 `guests @> '["馬世芳"]'` hard filter

#### Scenario: 沒抽出 entity 時走原 retrieval

- **WHEN** entity extractor 回 empty entities
- **THEN** retrieval 階段 MUST 不套用任何 metadata filter，走 R3.2 原本的 two-layer routing 路徑


<!-- @trace
source: r3-3-metadata-filter
updated: 2026-05-16
code:
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/eval/datasets/this-not-that-cool.json
  - docs/ai-steps.md
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/embedding.py
  - backend/app/services/rag.py
  - src/AdminTokenizerTab.jsx
  - index.html
  - backend/app/api/admin/__init__.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/tokenizer.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - src/App.jsx
  - backend/app/services/citation_parser.py
  - backend/app/schemas/query.py
  - backend/app/models/ai_step.py
  - src/AdminPage.jsx
  - backend/app/services/query_entity.py
  - backend/app/services/topic_segmentation.py
  - backend/app/models/episode.py
  - src/TranscriptPage.jsx
  - backend/scripts/backfill_guests.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/eval/datasets/_pending_review.json
  - CLAUDE.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/eval/datasets/_schema.json
  - backend/app/workers/topic_task.py
  - src/QueryPage.jsx
  - backend/scripts/backfill_topic_labels.py
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/app/schemas/episode_guests.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/api/shows.py
  - backend/app/api/query.py
  - backend/eval/metrics/recall.py
  - backend/eval/datasets/README.md
  - backend/app/services/rss_parser.py
  - docs/roadmap.md
  - backend/app/services/sync.py
  - backend/eval/scripts/validate_schema.py
  - src/ReleaseLogPage.jsx
  - backend/app/services/description_rechunker.py
  - src/releaseLog.jsx
  - backend/eval/runners/run.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/chunking_status.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/key_resolver.py
  - backend/app/models/transcript_chunk.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/Shared.jsx
  - backend/app/workers/celery_app.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/workers/tasks.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/app/schemas/query_entity.py
  - backend/eval/scripts/build_golden_set.py
tests:
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_topic_segmentation_persist.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_query_entity.py
-->

---
### Requirement: Entity 抽取作為可配置 AI Step

系統 SHALL 把 entity extractor 列為 admin 可配置的 AI step，admin 可不 redeploy 切換 model 或 provider。

#### Scenario: Admin 切換 model

- **WHEN** admin 在後台 AI Steps 頁面把 `entity_extraction` step 的 model 從 `gpt-4o-mini` 改成 `gemini-2.5-flash-lite`
- **THEN** 後續 chat query 的 entity 抽取 MUST 使用新 model，無需重啟服務

#### Scenario: Step 列表新增 entity_extraction

- **WHEN** 系統初始化或 migration 後
- **THEN** `ai_steps` 表 MUST 包含 step_id = `entity_extraction` 的 row，預設 model = `gpt-4o-mini`、預設 provider = OpenAI direct

<!-- @trace
source: r3-3-metadata-filter
updated: 2026-05-16
code:
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/eval/datasets/this-not-that-cool.json
  - docs/ai-steps.md
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/services/embedding.py
  - backend/app/services/rag.py
  - src/AdminTokenizerTab.jsx
  - index.html
  - backend/app/api/admin/__init__.py
  - backend/app/models/episode_description_chunk.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/tokenizer.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/services/llm_prompts.py
  - src/App.jsx
  - backend/app/services/citation_parser.py
  - backend/app/schemas/query.py
  - backend/app/models/ai_step.py
  - src/AdminPage.jsx
  - backend/app/services/query_entity.py
  - backend/app/services/topic_segmentation.py
  - backend/app/models/episode.py
  - src/TranscriptPage.jsx
  - backend/scripts/backfill_guests.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/eval/datasets/_pending_review.json
  - CLAUDE.md
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/eval/datasets/_schema.json
  - backend/app/workers/topic_task.py
  - src/QueryPage.jsx
  - backend/scripts/backfill_topic_labels.py
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - backend/app/schemas/episode_guests.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/api/shows.py
  - backend/app/api/query.py
  - backend/eval/metrics/recall.py
  - backend/eval/datasets/README.md
  - backend/app/services/rss_parser.py
  - docs/roadmap.md
  - backend/app/services/sync.py
  - backend/eval/scripts/validate_schema.py
  - src/ReleaseLogPage.jsx
  - backend/app/services/description_rechunker.py
  - src/releaseLog.jsx
  - backend/eval/runners/run.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/chunking_status.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/key_resolver.py
  - backend/app/models/transcript_chunk.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/Shared.jsx
  - backend/app/workers/celery_app.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/workers/tasks.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/app/schemas/query_entity.py
  - backend/eval/scripts/build_golden_set.py
tests:
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_topic_segmentation_persist.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_query_entity.py
-->