# processing-progress-overview Specification

## Purpose

TBD - created by archiving change 'backfill-progress-admin-tab'. Update Purpose after archive.

## Requirements

### Requirement: Processing stats admin endpoint

The backend SHALL expose `GET /admin/processing-stats` (admin role + CSRF required) returning JSON:

```json
{
  "transcription": {"completed_episodes": 414, "total_episodes": 556, "ratio": 0.745},
  "summary":       {"completed_episodes": 414, "total_episodes": 414, "ratio": 1.0},
  "topic_seg":     {"completed_segments": 277000, "total_segments": 700000, "ratio": 0.396, "completed_episodes": 113, "total_episodes_with_transcript": 414, "episode_ratio": 0.273},
  "last_24h": {
    "transcribed_episodes": 5,
    "labeled_segments": 47000,
    "failures": [{"task_name": "transcribe_episode", "count": 10, "sample_error": "413 Maximum content size limit exceeded"}, ...]
  },
  "as_of": "2026-05-10T11:30:00Z"
}
```

Numbers SHALL be computed via SQL queries on `episodes`, `transcripts`, `transcript_segments`. The `topic_seg` field SHALL include both `completed_segments / total_segments` (more precise) AND `completed_episodes / total_episodes_with_transcript` (per-episode count) so the frontend can show whichever matches the bar's intent. Failures in `last_24h` SHALL come from Celery result backend by scanning `celery-task-meta-*` keys with `status=FAILURE` and `date_done` within 24 hours, grouped by `task_name`. After F2 ships, the implementation SHALL switch to reading from `task_failure_log` table (same response shape).

#### Scenario: Endpoint returns three-dimensional progress

- **WHEN** admin calls `GET /admin/processing-stats`
- **THEN** the response SHALL be 200 JSON containing `transcription`, `summary`, `topic_seg`, `last_24h`, `as_of` keys

#### Scenario: topic_seg uses both segment and episode counts

- **GIVEN** there are 414 transcripts completed, 113 episodes have any topic_label, total transcript_segments = 700K, labeled = 277K
- **WHEN** admin calls the endpoint
- **THEN** the response SHALL contain `topic_seg.completed_segments=277000` AND `topic_seg.completed_episodes=113`
- **AND** SHALL include both `ratio=0.396` (segment ratio) and `episode_ratio=0.273` (episode ratio)

#### Scenario: last_24h failures grouped by task_name

- **GIVEN** Celery result backend has 10 FAILURE entries for transcribe_episode and 4 for classify_episode_topics within 24h
- **WHEN** admin calls the endpoint
- **THEN** `last_24h.failures` SHALL be `[{task_name: "app.workers.tasks.transcribe_episode", count: 10, sample_error: "..."}, {task_name: "app.workers.topic_task.classify_episode_topics", count: 4, sample_error: "..."}]`

#### Scenario: Non-admin gets 403

- **WHEN** a non-admin user calls the endpoint
- **THEN** the response SHALL be 403 Forbidden


<!-- @trace
source: backfill-progress-admin-tab
updated: 2026-05-18
code:
  - CLAUDE.md
  - backend/app/services/query_entity.py
  - src/ProviderUsageTab.jsx
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/models/episode_description_chunk.py
  - backend/scripts/backfill_guests.py
  - backend/app/services/episode_finders.py
  - src/App.jsx
  - backend/app/api/shows.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/.env.example
  - backend/app/schemas/query_entity.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/provider_usage/zeabur_aihub_adapter.py
  - backend/app/services/sync.py
  - backend/app/schemas/query.py
  - backend/app/services/citation_parser.py
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/services/transcription/openai_provider.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/models/transcript_chunk.py
  - src/QueueTab.jsx
  - backend/app/services/llm_prompts.py
  - src/AdminEpisodeGuestsTab.jsx
  - docs/ai-steps.md
  - backend/app/services/description_indexer.py
  - backend/app/workers/usage_collector.py
  - backend/app/services/tokenizer.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/eval/scripts/embedding_bakeoff.py
  - src/TranscriptPage.jsx
  - backend/app/models/__init__.py
  - backend/app/services/zsend.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/ai_step.py
  - src/QueryPage.jsx
  - backend/eval/scripts/build_golden_set.py
  - backend/app/services/provider_usage/__init__.py
  - backend/app/services/rag.py
  - backend/app/workers/celery_app.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/api/admin/chunking_status.py
  - src/releaseLog.jsx
  - backend/eval/datasets/_pending_review.json
  - backend/app/api/admin/episode_guests.py
  - src/AdminPage.jsx
  - backend/app/main.py
  - backend/app/api/admin_provider_usage.py
  - backend/app/services/key_resolver.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/models/episode.py
  - backend/app/services/description_rechunker.py
  - index.html
  - backend/eval/metrics/recall.py
  - backend/app/workers/tasks.py
  - backend/app/api/query.py
  - backend/app/api/admin/__init__.py
  - backend/eval/datasets/README.md
  - src/Shared.jsx
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/services/rss_parser.py
  - src/AdminTokenizerTab.jsx
  - backend/eval/scripts/validate_schema.py
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/eval/runners/run.py
  - backend/app/workers/usage_alert.py
  - docs/roadmap.md
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/app/core/config.py
  - backend/app/services/embedding.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/services/exceptions.py
  - backend/app/schemas/episode_guests.py
  - backend/eval/datasets/_schema.json
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
tests:
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_admin_episode_guests.py
-->

---
### Requirement: Admin Queue Tab shows processing overview

The admin frontend SHALL render a new `<ProcessingOverview>` block at the top of the existing Queue Tab page (above the per-row queue table). The block SHALL contain:

1. Three progress rows (轉錄 / 摘要 / 分類), each showing:
   - Label in zh + en (per CLAUDE.md i18n rule)
   - Progress bar (CSS-only, `<div>` with `width: <ratio>%`, no chart library)
   - Numeric ratio: `X / Y 集 (Z%)` for transcription / summary; `X / Y 段 (Z%)` for topic_seg (segment-level primary); also display `(M / N 集已完整標完)` in muted secondary text for topic_seg
2. "最近 24 小時" section:
   - "轉錄 +N 集 / 分類 +N 段（≈M 集邊際進度）/ 失敗 N 件"
   - "[查看失敗清單]" expandable button — click to expand a small table listing task_name × count × sample_error (truncated to 100 chars)
3. "上次更新：HH:MM 台北" small text bottom-right
4. Auto-poll every 30 seconds; on poll error show "更新失敗，重試中..." text without breaking the existing queue table below

The block SHALL appear regardless of whether queue table is empty (e.g. all completed). Time displayed in Asia/Taipei. All text bilingual (zh primary + en i18n key per existing pattern).

#### Scenario: All three progress rows render with bars

- **GIVEN** stats endpoint returns transcription ratio 0.745, summary 1.0, topic_seg ratio 0.396
- **WHEN** admin loads the Queue Tab
- **THEN** three progress rows SHALL render in order 轉錄 / 摘要 / 分類
- **AND** the bar widths SHALL be 74.5%, 100%, 39.6% respectively

#### Scenario: topic_seg shows segment AND episode counts

- **GIVEN** topic_seg.completed_segments=277000, total=700000, completed_episodes=113, total_episodes_with_transcript=414
- **WHEN** admin views the row
- **THEN** the row SHALL show "分類 — 277,000 / 700,000 段 (39.6%)"
- **AND** below it SHALL show in muted text "(113 / 414 集已完整標完)"

#### Scenario: 24h failures expandable

- **GIVEN** last_24h.failures contains 2 entries
- **WHEN** admin clicks "[查看失敗清單]" button
- **THEN** an inline table SHALL expand showing both entries with task_name and count
- **AND** clicking again SHALL collapse it

#### Scenario: 30s auto-poll updates ratios

- **GIVEN** the page is open with transcription ratio 0.74
- **AND** in the next 30 seconds, 5 more episodes complete transcription
- **WHEN** the polling interval fires
- **THEN** the displayed ratio SHALL update to reflect the new value

#### Scenario: Poll error shows transient warning

- **GIVEN** the /admin/processing-stats endpoint returns 500 once
- **WHEN** the poll fires
- **THEN** a small "更新失敗，重試中..." text SHALL appear inside the overview block
- **AND** the rest of the Queue Tab page (queue table) SHALL remain functional
- **AND** the next successful poll SHALL clear the warning

<!-- @trace
source: backfill-progress-admin-tab
updated: 2026-05-18
code:
  - CLAUDE.md
  - backend/app/services/query_entity.py
  - src/ProviderUsageTab.jsx
  - backend/eval/datasets/this-not-that-cool.json
  - backend/app/models/episode_description_chunk.py
  - backend/scripts/backfill_guests.py
  - backend/app/services/episode_finders.py
  - src/App.jsx
  - backend/app/api/shows.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/.env.example
  - backend/app/schemas/query_entity.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/app/services/provider_usage/zeabur_aihub_adapter.py
  - backend/app/services/sync.py
  - backend/app/schemas/query.py
  - backend/app/services/citation_parser.py
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/services/transcription/openai_provider.py
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/models/transcript_chunk.py
  - src/QueueTab.jsx
  - backend/app/services/llm_prompts.py
  - src/AdminEpisodeGuestsTab.jsx
  - docs/ai-steps.md
  - backend/app/services/description_indexer.py
  - backend/app/workers/usage_collector.py
  - backend/app/services/tokenizer.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/eval/scripts/embedding_bakeoff.py
  - src/TranscriptPage.jsx
  - backend/app/models/__init__.py
  - backend/app/services/zsend.py
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/ai_step.py
  - src/QueryPage.jsx
  - backend/eval/scripts/build_golden_set.py
  - backend/app/services/provider_usage/__init__.py
  - backend/app/services/rag.py
  - backend/app/workers/celery_app.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/api/admin/chunking_status.py
  - src/releaseLog.jsx
  - backend/eval/datasets/_pending_review.json
  - backend/app/api/admin/episode_guests.py
  - src/AdminPage.jsx
  - backend/app/main.py
  - backend/app/api/admin_provider_usage.py
  - backend/app/services/key_resolver.py
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/models/episode.py
  - backend/app/services/description_rechunker.py
  - index.html
  - backend/eval/metrics/recall.py
  - backend/app/workers/tasks.py
  - backend/app/api/query.py
  - backend/app/api/admin/__init__.py
  - backend/eval/datasets/README.md
  - src/Shared.jsx
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/services/rss_parser.py
  - src/AdminTokenizerTab.jsx
  - backend/eval/scripts/validate_schema.py
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/eval/runners/run.py
  - backend/app/workers/usage_alert.py
  - docs/roadmap.md
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - backend/app/core/config.py
  - backend/app/services/embedding.py
  - backend/scripts/cleanup_v1_description_chunks.py
  - backend/app/services/exceptions.py
  - backend/app/schemas/episode_guests.py
  - backend/eval/datasets/_schema.json
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
tests:
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_description_rechunker.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_admin_episode_guests.py
-->