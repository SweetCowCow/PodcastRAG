# provider-usage-monitoring Specification

## Purpose

TBD - created by archiving change 'multi-provider-usage-monitoring'. Update Purpose after archive.

## Requirements

### Requirement: Provider usage snapshot table

The backend SHALL maintain a `provider_usage_snapshot` table with columns: `id` (UUID PK), `provider` (string: `aihub`, `openai`, plus future identifiers), `model` (nullable string), `date` (date), `spend_usd` (numeric(10,4)), `raw_payload` (jsonb), `fetched_at` (timestamptz). The table SHALL have a unique constraint on `(provider, model, date)` so re-fetching the same day overwrites rather than duplicates. New providers SHALL be added by inserting rows with new `provider` values without any schema change.

#### Scenario: First fetch inserts row

- **GIVEN** the table has no rows for `(aihub, gpt-4o-mini, 2026-05-10)`
- **WHEN** the usage collector inserts `(aihub, gpt-4o-mini, 2026-05-10, 1.23, {...}, NOW())`
- **THEN** exactly one row SHALL exist with those values

#### Scenario: Re-fetch upserts the row

- **GIVEN** a row `(aihub, gpt-4o-mini, 2026-05-10, 1.23, ...)` already exists
- **WHEN** the collector re-fetches and the new daily total is 2.45
- **THEN** the row SHALL be updated (not duplicated) to `spend_usd=2.45`, `fetched_at=NOW()`

#### Scenario: New provider adds rows without migration

- **GIVEN** a new adapter for `deepgram` is added to the registry
- **WHEN** the collector calls the deepgram adapter and writes its results
- **THEN** rows with `provider='deepgram'` SHALL be inserted into the same table


<!-- @trace
source: multi-provider-usage-monitoring
updated: 2026-05-18
code:
  - backend/app/api/admin/chunking_status.py
  - backend/eval/datasets/_pending_review.json
  - backend/app/services/key_resolver.py
  - backend/eval/runners/run.py
  - src/QueueTab.jsx
  - backend/app/services/tokenizer.py
  - backend/app/services/embedding.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/services/episode_finders.py
  - backend/app/services/rss_parser.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/eval/datasets/this-not-that-cool.json
  - CLAUDE.md
  - docs/roadmap.md
  - src/Shared.jsx
  - backend/app/services/exceptions.py
  - backend/app/workers/usage_collector.py
  - backend/app/schemas/query_entity.py
  - backend/app/services/transcription/openai_provider.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/models/__init__.py
  - src/App.jsx
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/schemas/episode_guests.py
  - backend/eval/metrics/recall.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/provider_usage/__init__.py
  - src/AdminPage.jsx
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/main.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/services/sync.py
  - backend/app/services/zsend.py
  - backend/app/workers/tasks.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/api/admin/__init__.py
  - index.html
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/episode.py
  - backend/app/services/rag.py
  - backend/app/services/citation_parser.py
  - backend/app/services/provider_usage/zeabur_aihub_adapter.py
  - backend/eval/datasets/_schema.json
  - backend/eval/scripts/build_golden_set.py
  - src/TranscriptPage.jsx
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - src/ProviderUsageTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/services/description_rechunker.py
  - backend/.env.example
  - docs/ai-steps.md
  - backend/app/models/transcript_chunk.py
  - src/AdminTokenizerTab.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - src/releaseLog.jsx
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/core/config.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/services/query_entity.py
  - backend/app/api/admin_provider_usage.py
  - backend/app/workers/usage_alert.py
  - backend/scripts/backfill_guests.py
  - backend/eval/datasets/README.md
  - backend/app/models/episode_description_chunk.py
  - backend/app/schemas/query.py
  - backend/app/api/shows.py
  - backend/app/models/ai_step.py
  - backend/app/workers/celery_app.py
  - backend/app/api/query.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/ai_steps.py
  - src/QueryPage.jsx
tests:
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_rechunker.py
-->

---
### Requirement: Adapter interface for provider usage

The backend SHALL expose a uniform adapter interface in `app.services.provider_usage`. Each adapter module SHALL implement the function signature `async def fetch_daily_usage(start: date, end: date) -> list[UsageSnapshot]` where `UsageSnapshot` is a dataclass with fields `(provider: str, model: str | None, date: date, spend_usd: Decimal, raw_payload: dict)`. Adapters SHALL be registered in `provider_usage/__init__.py` `ADAPTERS: dict[str, Callable]` so the collector iterates them generically.

#### Scenario: AI Hub adapter returns daily usage

- **GIVEN** `ADAPTERS['aihub']` is the Zeabur AI Hub adapter
- **WHEN** `await ADAPTERS['aihub'](date(2026, 5, 1), date(2026, 5, 10))` is called
- **THEN** the return value SHALL be `list[UsageSnapshot]` with provider='aihub' for every snapshot

#### Scenario: OpenAI adapter returns daily usage

- **GIVEN** `ADAPTERS['openai']` is the OpenAI direct adapter
- **WHEN** `await ADAPTERS['openai'](date(2026, 5, 1), date(2026, 5, 10))` is called
- **THEN** the return value SHALL be `list[UsageSnapshot]` with provider='openai' for every snapshot

#### Scenario: Adapter without admin key gracefully returns empty

- **GIVEN** OpenAI adapter is invoked but `OPENAI_ORG_ADMIN_KEY` env is unset
- **WHEN** `fetch_daily_usage(...)` runs
- **THEN** the adapter SHALL log a warning "OPENAI_ORG_ADMIN_KEY not configured, skipping"
- **AND** SHALL return an empty list (no exception raised)


<!-- @trace
source: multi-provider-usage-monitoring
updated: 2026-05-18
code:
  - backend/app/api/admin/chunking_status.py
  - backend/eval/datasets/_pending_review.json
  - backend/app/services/key_resolver.py
  - backend/eval/runners/run.py
  - src/QueueTab.jsx
  - backend/app/services/tokenizer.py
  - backend/app/services/embedding.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/services/episode_finders.py
  - backend/app/services/rss_parser.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/eval/datasets/this-not-that-cool.json
  - CLAUDE.md
  - docs/roadmap.md
  - src/Shared.jsx
  - backend/app/services/exceptions.py
  - backend/app/workers/usage_collector.py
  - backend/app/schemas/query_entity.py
  - backend/app/services/transcription/openai_provider.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/models/__init__.py
  - src/App.jsx
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/schemas/episode_guests.py
  - backend/eval/metrics/recall.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/provider_usage/__init__.py
  - src/AdminPage.jsx
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/main.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/services/sync.py
  - backend/app/services/zsend.py
  - backend/app/workers/tasks.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/api/admin/__init__.py
  - index.html
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/episode.py
  - backend/app/services/rag.py
  - backend/app/services/citation_parser.py
  - backend/app/services/provider_usage/zeabur_aihub_adapter.py
  - backend/eval/datasets/_schema.json
  - backend/eval/scripts/build_golden_set.py
  - src/TranscriptPage.jsx
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - src/ProviderUsageTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/services/description_rechunker.py
  - backend/.env.example
  - docs/ai-steps.md
  - backend/app/models/transcript_chunk.py
  - src/AdminTokenizerTab.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - src/releaseLog.jsx
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/core/config.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/services/query_entity.py
  - backend/app/api/admin_provider_usage.py
  - backend/app/workers/usage_alert.py
  - backend/scripts/backfill_guests.py
  - backend/eval/datasets/README.md
  - backend/app/models/episode_description_chunk.py
  - backend/app/schemas/query.py
  - backend/app/api/shows.py
  - backend/app/models/ai_step.py
  - backend/app/workers/celery_app.py
  - backend/app/api/query.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/ai_steps.py
  - src/QueryPage.jsx
tests:
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_rechunker.py
-->

---
### Requirement: Hourly usage collector beat task

The backend SHALL register a Celery Beat schedule entry `usage-collector` running every hour on the hour (cron `0 * * * *`). The handler SHALL iterate every adapter in `ADAPTERS`, call `fetch_daily_usage(start=yesterday, end=today)`, and upsert each `UsageSnapshot` into `provider_usage_snapshot`. If one adapter raises, the collector SHALL log the error and continue with remaining adapters (per-adapter isolation).

#### Scenario: All adapters succeed

- **GIVEN** ADAPTERS = {aihub, openai} both healthy
- **WHEN** the usage-collector beat task runs
- **THEN** rows for both providers covering yesterday and today SHALL be upserted
- **AND** the handler SHALL log success counts per provider

#### Scenario: One adapter fails, other succeeds

- **GIVEN** the openai adapter raises `httpx.TimeoutException` but aihub succeeds
- **WHEN** the usage-collector beat task runs
- **THEN** aihub rows SHALL still be written
- **AND** the openai failure SHALL be logged with `exc_info=True`
- **AND** the handler SHALL exit normally (no Celery retry, the next hourly tick will try openai again)


<!-- @trace
source: multi-provider-usage-monitoring
updated: 2026-05-18
code:
  - backend/app/api/admin/chunking_status.py
  - backend/eval/datasets/_pending_review.json
  - backend/app/services/key_resolver.py
  - backend/eval/runners/run.py
  - src/QueueTab.jsx
  - backend/app/services/tokenizer.py
  - backend/app/services/embedding.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/services/episode_finders.py
  - backend/app/services/rss_parser.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/eval/datasets/this-not-that-cool.json
  - CLAUDE.md
  - docs/roadmap.md
  - src/Shared.jsx
  - backend/app/services/exceptions.py
  - backend/app/workers/usage_collector.py
  - backend/app/schemas/query_entity.py
  - backend/app/services/transcription/openai_provider.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/models/__init__.py
  - src/App.jsx
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/schemas/episode_guests.py
  - backend/eval/metrics/recall.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/provider_usage/__init__.py
  - src/AdminPage.jsx
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/main.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/services/sync.py
  - backend/app/services/zsend.py
  - backend/app/workers/tasks.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/api/admin/__init__.py
  - index.html
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/episode.py
  - backend/app/services/rag.py
  - backend/app/services/citation_parser.py
  - backend/app/services/provider_usage/zeabur_aihub_adapter.py
  - backend/eval/datasets/_schema.json
  - backend/eval/scripts/build_golden_set.py
  - src/TranscriptPage.jsx
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - src/ProviderUsageTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/services/description_rechunker.py
  - backend/.env.example
  - docs/ai-steps.md
  - backend/app/models/transcript_chunk.py
  - src/AdminTokenizerTab.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - src/releaseLog.jsx
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/core/config.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/services/query_entity.py
  - backend/app/api/admin_provider_usage.py
  - backend/app/workers/usage_alert.py
  - backend/scripts/backfill_guests.py
  - backend/eval/datasets/README.md
  - backend/app/models/episode_description_chunk.py
  - backend/app/schemas/query.py
  - backend/app/api/shows.py
  - backend/app/models/ai_step.py
  - backend/app/workers/celery_app.py
  - backend/app/api/query.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/ai_steps.py
  - src/QueryPage.jsx
tests:
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_rechunker.py
-->

---
### Requirement: Daily usage threshold alert beat task

The backend SHALL register a Celery Beat schedule entry `usage-alert` running daily at 09:00 Asia/Taipei (cron `0 1 * * *` in UTC = 09:00 Taipei). The handler SHALL evaluate per provider:

1. Compute current calendar month accumulated spend: `SELECT SUM(spend_usd) FROM provider_usage_snapshot WHERE provider=:p AND date_trunc('month', date) = date_trunc('month', NOW())`
2. Compare against `provider_budget_usd_monthly[provider]` config (v1 hardcoded: aihub=80, openai=30)
3. If ratio >= 0.95 → red severity; else if ratio >= 0.80 → yellow severity; else no alert
4. Per provider per severity per UTC day, send at most one ZSend alert. Track in `usage_alert_log` table `(provider, severity, alerted_date PK)` to dedupe.

The alert email SHALL contain provider name, accumulated spend, budget, ratio percentage, top 3 models by spend this month, link hint to admin UI.

#### Scenario: 80% triggers yellow alert

- **GIVEN** aihub provider has accumulated $65 of $80 monthly budget (81%)
- **AND** no yellow alert was sent today for aihub
- **WHEN** the usage-alert beat task runs
- **THEN** exactly one ZSend yellow alert SHALL be sent for aihub
- **AND** `usage_alert_log` SHALL have row `(aihub, yellow, 2026-05-10)`

#### Scenario: 95% triggers red alert

- **GIVEN** aihub accumulated $77 of $80 (96%)
- **WHEN** the task runs
- **THEN** one ZSend red alert SHALL be sent
- **AND** no yellow alert SHALL be sent (red supersedes)

#### Scenario: Already-alerted today not re-alerted

- **GIVEN** aihub yellow alert was sent earlier today (`usage_alert_log` has row)
- **AND** ratio is still 82%
- **WHEN** the task runs
- **THEN** no new alert SHALL be sent

#### Scenario: Below 80% no alert

- **GIVEN** aihub accumulated $40 of $80 (50%)
- **WHEN** the task runs
- **THEN** no alert SHALL be sent


<!-- @trace
source: multi-provider-usage-monitoring
updated: 2026-05-18
code:
  - backend/app/api/admin/chunking_status.py
  - backend/eval/datasets/_pending_review.json
  - backend/app/services/key_resolver.py
  - backend/eval/runners/run.py
  - src/QueueTab.jsx
  - backend/app/services/tokenizer.py
  - backend/app/services/embedding.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/services/episode_finders.py
  - backend/app/services/rss_parser.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/eval/datasets/this-not-that-cool.json
  - CLAUDE.md
  - docs/roadmap.md
  - src/Shared.jsx
  - backend/app/services/exceptions.py
  - backend/app/workers/usage_collector.py
  - backend/app/schemas/query_entity.py
  - backend/app/services/transcription/openai_provider.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/models/__init__.py
  - src/App.jsx
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/schemas/episode_guests.py
  - backend/eval/metrics/recall.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/provider_usage/__init__.py
  - src/AdminPage.jsx
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/main.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/services/sync.py
  - backend/app/services/zsend.py
  - backend/app/workers/tasks.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/api/admin/__init__.py
  - index.html
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/episode.py
  - backend/app/services/rag.py
  - backend/app/services/citation_parser.py
  - backend/app/services/provider_usage/zeabur_aihub_adapter.py
  - backend/eval/datasets/_schema.json
  - backend/eval/scripts/build_golden_set.py
  - src/TranscriptPage.jsx
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - src/ProviderUsageTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/services/description_rechunker.py
  - backend/.env.example
  - docs/ai-steps.md
  - backend/app/models/transcript_chunk.py
  - src/AdminTokenizerTab.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - src/releaseLog.jsx
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/core/config.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/services/query_entity.py
  - backend/app/api/admin_provider_usage.py
  - backend/app/workers/usage_alert.py
  - backend/scripts/backfill_guests.py
  - backend/eval/datasets/README.md
  - backend/app/models/episode_description_chunk.py
  - backend/app/schemas/query.py
  - backend/app/api/shows.py
  - backend/app/models/ai_step.py
  - backend/app/workers/celery_app.py
  - backend/app/api/query.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/ai_steps.py
  - src/QueryPage.jsx
tests:
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_rechunker.py
-->

---
### Requirement: Admin REST endpoint for usage data

The backend SHALL expose admin-only REST endpoints (require admin role + CSRF):

- `GET /admin/provider-usage/daily?start=<date>&end=<date>` returns JSON list of `(provider, model, date, spend_usd)` rows in the range
- `GET /admin/provider-usage/monthly` returns JSON `{provider: {budget_usd, accumulated_usd, ratio, top_models: [{model, spend_usd}]}}` for current calendar month, all providers

Times in ISO 8601 UTC. Frontend SHALL convert to Asia/Taipei for display.

#### Scenario: Daily endpoint returns 30-day data

- **WHEN** admin calls `GET /admin/provider-usage/daily?start=2026-04-11&end=2026-05-10`
- **THEN** the response SHALL be a 200 JSON array containing rows for both providers in that range

#### Scenario: Monthly endpoint returns ratios

- **GIVEN** aihub accumulated $35 of $80 budget, openai $10 of $30
- **WHEN** admin calls `GET /admin/provider-usage/monthly`
- **THEN** the response SHALL include `aihub.ratio = 0.4375` and `openai.ratio = 0.3333`
- **AND** `top_models` SHALL list each provider's top 3 spending models for the month

#### Scenario: Non-admin gets 403

- **WHEN** a non-admin user calls either endpoint
- **THEN** the response SHALL be 403 Forbidden


<!-- @trace
source: multi-provider-usage-monitoring
updated: 2026-05-18
code:
  - backend/app/api/admin/chunking_status.py
  - backend/eval/datasets/_pending_review.json
  - backend/app/services/key_resolver.py
  - backend/eval/runners/run.py
  - src/QueueTab.jsx
  - backend/app/services/tokenizer.py
  - backend/app/services/embedding.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/services/episode_finders.py
  - backend/app/services/rss_parser.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/eval/datasets/this-not-that-cool.json
  - CLAUDE.md
  - docs/roadmap.md
  - src/Shared.jsx
  - backend/app/services/exceptions.py
  - backend/app/workers/usage_collector.py
  - backend/app/schemas/query_entity.py
  - backend/app/services/transcription/openai_provider.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/models/__init__.py
  - src/App.jsx
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/schemas/episode_guests.py
  - backend/eval/metrics/recall.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/provider_usage/__init__.py
  - src/AdminPage.jsx
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/main.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/services/sync.py
  - backend/app/services/zsend.py
  - backend/app/workers/tasks.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/api/admin/__init__.py
  - index.html
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/episode.py
  - backend/app/services/rag.py
  - backend/app/services/citation_parser.py
  - backend/app/services/provider_usage/zeabur_aihub_adapter.py
  - backend/eval/datasets/_schema.json
  - backend/eval/scripts/build_golden_set.py
  - src/TranscriptPage.jsx
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - src/ProviderUsageTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/services/description_rechunker.py
  - backend/.env.example
  - docs/ai-steps.md
  - backend/app/models/transcript_chunk.py
  - src/AdminTokenizerTab.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - src/releaseLog.jsx
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/core/config.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/services/query_entity.py
  - backend/app/api/admin_provider_usage.py
  - backend/app/workers/usage_alert.py
  - backend/scripts/backfill_guests.py
  - backend/eval/datasets/README.md
  - backend/app/models/episode_description_chunk.py
  - backend/app/schemas/query.py
  - backend/app/api/shows.py
  - backend/app/models/ai_step.py
  - backend/app/workers/celery_app.py
  - backend/app/api/query.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/ai_steps.py
  - src/QueryPage.jsx
tests:
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_rechunker.py
-->

---
### Requirement: Admin UI shows usage chart and budget banner

The admin frontend SHALL add a new tab "服務用量" (Service Usage) at route `page='admin-provider-usage'`, accessible from the admin sidebar nav. The tab SHALL render:

1. Top banner per provider:
   - Yellow banner if `ratio >= 0.80 && < 0.95` with text "<provider> 用量已達 <ratio>%（$<spend> / $<budget>）— 留意是否需要充值"
   - Red banner if `ratio >= 0.95` with text "<provider> 用量已達 <ratio>% — 請立即至 Zeabur / OpenAI 後台充值，否則服務將中斷"
2. Per-provider summary card: monthly budget, accumulated spend, ratio bar, top 3 models with $ amounts
3. 30-day stacked SVG bar chart: x-axis = date (Asia/Taipei), y-axis = spend USD, one stacked column per day per provider, hover SHALL show tooltip with date + per-provider $ breakdown

The UI SHALL refresh every 60 seconds via polling. All text in 繁體中文 + 英文 i18n key.

The 操作 area SHALL NOT contain any auto-recharge button. Instead, the red banner SHALL contain a static link "前往 Zeabur AI Hub" / "前往 OpenAI dashboard" opening in new tab.

#### Scenario: Yellow ratio shows yellow banner

- **GIVEN** aihub ratio is 0.82
- **WHEN** admin views the tab
- **THEN** a yellow banner SHALL appear at top with text containing "aihub 用量已達 82%"

#### Scenario: Red ratio shows red banner with external link

- **GIVEN** aihub ratio is 0.97
- **WHEN** admin views the tab
- **THEN** a red banner SHALL appear with text containing "aihub 用量已達 97%"
- **AND** a link "前往 Zeabur AI Hub" SHALL be present opening `https://dash.zeabur.com/` in new tab

#### Scenario: 30-day chart hover tooltip

- **GIVEN** the chart shows 30 daily bars per provider
- **WHEN** admin hovers over the 2026-05-09 bar
- **THEN** a tooltip SHALL appear with text "2026-05-09 台北 — aihub: $35.16 / openai: $0.50"

#### Scenario: No auto-recharge button rendered

- **WHEN** admin views the tab regardless of ratio
- **THEN** no button labelled "auto-recharge" / "自動充值" / "啟用扣款" SHALL be present

<!-- @trace
source: multi-provider-usage-monitoring
updated: 2026-05-18
code:
  - backend/app/api/admin/chunking_status.py
  - backend/eval/datasets/_pending_review.json
  - backend/app/services/key_resolver.py
  - backend/eval/runners/run.py
  - src/QueueTab.jsx
  - backend/app/services/tokenizer.py
  - backend/app/services/embedding.py
  - backend/alembic/versions/w1d2e3f4a5b6_r33_add_entity_extraction_step.py
  - backend/app/services/episode_finders.py
  - backend/app/services/rss_parser.py
  - backend/alembic/versions/t8a9b0c1d2e3_chunking_version_description_chunks.py
  - backend/eval/datasets/this-not-that-cool.json
  - CLAUDE.md
  - docs/roadmap.md
  - src/Shared.jsx
  - backend/app/services/exceptions.py
  - backend/app/workers/usage_collector.py
  - backend/app/schemas/query_entity.py
  - backend/app/services/transcription/openai_provider.py
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
  - src/AdminEpisodeGuestsTab.jsx
  - backend/app/models/__init__.py
  - src/App.jsx
  - backend/scripts/backfill_embedding_v2.py
  - backend/app/schemas/episode_guests.py
  - backend/eval/metrics/recall.py
  - backend/scripts/backfill_title_tsv.py
  - backend/app/services/provider_usage/__init__.py
  - src/AdminPage.jsx
  - backend/alembic/versions/x2e3f4a5b6c7_provider_usage_monitoring.py
  - backend/app/services/provider_usage/openai_adapter.py
  - backend/app/main.py
  - backend/eval/scripts/validate_schema.py
  - backend/app/api/admin_processing_stats.py
  - backend/app/services/sync.py
  - backend/app/services/zsend.py
  - backend/app/workers/tasks.py
  - backend/app/models/provider_usage_snapshot.py
  - backend/app/api/admin/__init__.py
  - index.html
  - backend/scripts/pilot_reembed_descriptions.py
  - backend/app/models/episode.py
  - backend/app/services/rag.py
  - backend/app/services/citation_parser.py
  - backend/app/services/provider_usage/zeabur_aihub_adapter.py
  - backend/eval/datasets/_schema.json
  - backend/eval/scripts/build_golden_set.py
  - src/TranscriptPage.jsx
  - backend/alembic/versions/v0c1d2e3f4a5_r33_episodes_guests_and_title_tsv.py
  - src/ProviderUsageTab.jsx
  - backend/app/services/llm_prompts.py
  - backend/app/services/description_rechunker.py
  - backend/.env.example
  - docs/ai-steps.md
  - backend/app/models/transcript_chunk.py
  - src/AdminTokenizerTab.jsx
  - backend/scripts/cleanup_v1_description_chunks.py
  - src/releaseLog.jsx
  - backend/eval/scripts/bakeoff_entity_extractor.py
  - backend/app/core/config.py
  - backend/eval/scripts/embedding_bakeoff.py
  - backend/app/services/description_indexer.py
  - backend/alembic/versions/u9b0c1d2e3f4_add_embedding_v2_columns.py
  - backend/app/services/query_entity.py
  - backend/app/api/admin_provider_usage.py
  - backend/app/workers/usage_alert.py
  - backend/scripts/backfill_guests.py
  - backend/eval/datasets/README.md
  - backend/app/models/episode_description_chunk.py
  - backend/app/schemas/query.py
  - backend/app/api/shows.py
  - backend/app/models/ai_step.py
  - backend/app/workers/celery_app.py
  - backend/app/api/query.py
  - backend/app/api/admin/episode_guests.py
  - backend/app/api/admin/ai_steps.py
  - src/QueryPage.jsx
tests:
  - backend/tests/test_description_retrieval_prefer_v2.py
  - backend/tests/test_compute_enumeration_combiner.py
  - backend/tests/test_backfill_guests.py
  - backend/tests/test_usage_collector.py
  - backend/tests/test_episode_guests_schema.py
  - backend/tests/test_query_entity.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_openai_provider_chunking.py
  - backend/tests/test_chunking_version_coexistence.py
  - backend/tests/test_answer_malformed_json_salvage.py
  - backend/tests/test_rag_retrieval_flags.py
  - backend/tests/test_key_resolver.py
  - backend/tests/test_admin_processing_stats_api.py
  - backend/tests/test_strip_citations.py
  - backend/tests/test_eval_dataset_schema.py
  - backend/tests/test_runner_chat_enumeration.py
  - backend/tests/test_provider_usage_adapters.py
  - backend/tests/test_admin_provider_usage_api.py
  - backend/tests/test_citation_parser.py
  - backend/tests/test_rag_multi_column_bm25.py
  - backend/tests/test_query_chat_metadata_filter.py
  - backend/tests/test_admin_episode_guests.py
  - backend/tests/test_rag_query_response_shape.py
  - backend/tests/test_description_chunker_120.py
  - backend/tests/test_usage_alert.py
  - backend/tests/test_rss_guests_extraction.py
  - backend/tests/test_ai_summary_full_field.py
  - backend/tests/test_episode_finders.py
  - backend/tests/test_rag_embedding_v2_flag.py
  - backend/tests/test_eval_runner_flags.py
  - backend/tests/test_llm_prompts.py
  - backend/tests/test_chat_enum_grounding.py
  - backend/tests/test_embedding_v2_dual_write.py
  - backend/tests/test_answer_unwrap.py
  - backend/tests/test_eval_runner_dispatch.py
  - backend/tests/test_description_rechunker.py
-->