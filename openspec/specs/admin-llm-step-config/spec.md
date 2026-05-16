# admin-llm-step-config Specification

## Purpose

TBD - created by archiving change 'admin-llm-step-config'. Update Purpose after archive.

## Requirements

### Requirement: API key registry table

The backend SHALL maintain an `api_keys` table that stores credentials for AI providers as a separate row each. Columns SHALL include `id` (UUID, PK), `provider` (VARCHAR(50), free-form lower-case identifier such as `openai` / `anthropic` / `google` / `zeabur-aihub`), `label` (VARCHAR(100), human-readable name), `api_key` (TEXT, plaintext for now), `created_at` (TIMESTAMP UTC, server default `now()`), `updated_at` (TIMESTAMP UTC, server default `now()`). The combination `(provider, label)` SHALL be UNIQUE so the same provider can have multiple labelled keys but not two with the same label.

#### Scenario: Create a new API key entry

- **WHEN** an admin POSTs `/admin/api-keys` with `{ provider: "openai", label: "main", api_key: "sk-..." }`
- **THEN** the backend SHALL insert a new row, return `200` with `{ id, provider, label, api_key_masked, created_at }` (api_key SHALL be returned masked, e.g. last 4 chars only) and SHALL NOT echo the raw key

#### Scenario: Reject duplicate (provider, label)

- **GIVEN** an `api_keys` row exists with `provider="openai", label="main"`
- **WHEN** an admin POSTs another with the same `provider` and `label`
- **THEN** the backend SHALL return `409 Conflict` with body `{ detail: "duplicate label for provider" }` (or zh-tw equivalent at API caller's choice)

#### Scenario: Soft delete blocked when key in use

- **GIVEN** an `ai_steps` row references `api_key_id = X`
- **WHEN** an admin DELETEs `/admin/api-keys/X`
- **THEN** the backend SHALL return `409 Conflict` with body listing the referencing `step_key`s, and the row SHALL NOT be deleted


<!-- @trace
source: admin-llm-step-config
updated: 2026-05-03
code:
  - backend/alembic/versions/m1b2c3d4e5f6_drop_llm_config.py
  - backend/app/services/transcription/openai_provider.py
  - src/Shared.jsx
  - backend/app/main.py
  - backend/app/services/embedding.py
  - backend/app/services/transcription/factory.py
  - docs/research/competitive-analysis.md
  - backend/app/schemas/api_key.py
  - backend/app/api/admin/api_keys.py
  - backend/app/schemas/ai_step.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/core/config.py
  - aisteps-tab.png
  - backend/app/core/bootstrap.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - backend/app/api/query.py
  - backend/app/models/__init__.py
  - backend/app/api/admin/__init__.py
  - backend/app/schemas/admin.py
  - backend/alembic/versions/l0a1b2c3d4e5_add_api_keys_and_ai_steps.py
  - backend/app/services/ai_step_resolver.py
  - index.html
  - src/AdminPage.jsx
  - docs/research/competitive-feature-plan.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/llm_config.py
  - backend/app/api/admin.py
  - backend/app/workers/tasks.py
  - backend/app/models/ai_step.py
  - backend/app/services/llm_config.py
  - src/releaseLog.jsx
  - backend/app/models/api_key.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/roadmap.md
tests:
  - backend/tests/test_ai_step_resolver.py
  - backend/tests/test_admin_ai_steps.py
  - backend/tests/test_admin_llm_step_migration.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_admin_api_keys.py
  - backend/tests/test_provider_label.py
-->

---
### Requirement: AI step configuration table with hardcoded step keys

The backend SHALL maintain an `ai_steps` table where each row represents one AI processing endpoint used by the application. Columns SHALL include `step_key` (VARCHAR(50), PK), `step_type` (VARCHAR(20), one of `chat` / `embedding` / `whisper`), `base_url` (VARCHAR(500), nullable for whisper-local), `model` (VARCHAR(200)), `api_key_id` (UUID FK to `api_keys.id`, nullable for whisper-local), `extra_config` (JSONB, default `{}`), `updated_at` (TIMESTAMP UTC).

A CHECK constraint SHALL restrict `step_key` to exactly the following six values: `answer`, `rewrite`, `summary`, `embedding`, `transcription`, `entity_extraction`. The migration that creates this table SHALL pre-insert one row per `step_key` so callers always observe exactly six rows. The CRUD API SHALL expose only LIST and UPDATE; CREATE and DELETE SHALL return `405 Method Not Allowed`.

#### Scenario: Pre-existing six rows after migration

- **WHEN** the migration that adds `entity_extraction` step finishes
- **THEN** `SELECT step_key FROM ai_steps ORDER BY step_key` SHALL return exactly: `answer`, `embedding`, `entity_extraction`, `rewrite`, `summary`, `transcription`

#### Scenario: List returns all six rows even if some are unconfigured

- **WHEN** an admin GETs `/admin/ai-steps`
- **THEN** the backend SHALL return a JSON array of six objects, each with `{ step_key, step_type, base_url, model, api_key_id, extra_config, updated_at }`. Unconfigured rows SHALL still be present, with `base_url` / `model` / `api_key_id` set to null when the admin has not configured them yet

#### Scenario: Reject CREATE attempt

- **WHEN** any client POSTs `/admin/ai-steps`
- **THEN** the backend SHALL return `405 Method Not Allowed`

#### Scenario: Reject step_key outside hardcoded set in UPDATE

- **WHEN** an admin PUTs `/admin/ai-steps/foo`
- **THEN** the backend SHALL return `404 Not Found`

#### Scenario: entity_extraction defaults to gpt-4o-mini at OpenAI direct

- **WHEN** the migration that adds `entity_extraction` step runs
- **THEN** the inserted row MUST have `step_type='chat'`, `model='gpt-4o-mini'`, `base_url=NULL` (OpenAI default), `api_key_id` pointing to the OpenAI provider key (if exactly one OpenAI api_key exists; otherwise left NULL for admin to configure)

##### Example: step_type assignment

| step_key | step_type |
|----------|-----------|
| answer | chat |
| rewrite | chat |
| summary | chat |
| entity_extraction | chat |
| embedding | embedding |
| transcription | whisper |


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
### Requirement: Embedding step provider restriction

The backend SHALL reject any `PUT /admin/ai-steps/embedding` request whose `api_key_id` references an `api_keys` row with `provider != "openai"`. The frontend SHALL filter the api_key dropdown for the embedding step to show only `provider == "openai"` keys.

#### Scenario: Backend rejects non-OpenAI provider for embedding step

- **GIVEN** an `api_keys` row exists with `id=K1, provider="anthropic"`
- **WHEN** an admin PUTs `/admin/ai-steps/embedding` with `{ api_key_id: "K1", base_url: "...", model: "..." }`
- **THEN** the backend SHALL return `422 Unprocessable Entity` with body `{ detail: "embedding step requires an openai-provider api_key" }` (or zh-tw equivalent) and the row SHALL NOT be updated

#### Scenario: Frontend dropdown filters embedding api_key options

- **GIVEN** `api_keys` contains `{provider: openai, label: A}`, `{provider: anthropic, label: B}`, `{provider: zeabur-aihub, label: C}`
- **WHEN** the admin opens the embedding step form in `AiStepsTab`
- **THEN** the api_key dropdown SHALL show only the OpenAI entry; the other two SHALL NOT appear


<!-- @trace
source: admin-llm-step-config
updated: 2026-05-03
code:
  - backend/alembic/versions/m1b2c3d4e5f6_drop_llm_config.py
  - backend/app/services/transcription/openai_provider.py
  - src/Shared.jsx
  - backend/app/main.py
  - backend/app/services/embedding.py
  - backend/app/services/transcription/factory.py
  - docs/research/competitive-analysis.md
  - backend/app/schemas/api_key.py
  - backend/app/api/admin/api_keys.py
  - backend/app/schemas/ai_step.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/core/config.py
  - aisteps-tab.png
  - backend/app/core/bootstrap.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - backend/app/api/query.py
  - backend/app/models/__init__.py
  - backend/app/api/admin/__init__.py
  - backend/app/schemas/admin.py
  - backend/alembic/versions/l0a1b2c3d4e5_add_api_keys_and_ai_steps.py
  - backend/app/services/ai_step_resolver.py
  - index.html
  - src/AdminPage.jsx
  - docs/research/competitive-feature-plan.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/llm_config.py
  - backend/app/api/admin.py
  - backend/app/workers/tasks.py
  - backend/app/models/ai_step.py
  - backend/app/services/llm_config.py
  - src/releaseLog.jsx
  - backend/app/models/api_key.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/roadmap.md
tests:
  - backend/tests/test_ai_step_resolver.py
  - backend/tests/test_admin_ai_steps.py
  - backend/tests/test_admin_llm_step_migration.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_admin_api_keys.py
  - backend/tests/test_provider_label.py
-->

---
### Requirement: Backend service layer reads from ai_steps via resolver

The backend services that perform LLM, embedding, or transcription work (`services/rag.py`, `services/embedding.py`, `services/transcription/factory.py` and the two whisper providers) SHALL read their endpoint, api_key, model, and step-specific config from `ai_steps` (joined with `api_keys`) at request time. They SHALL NOT read directly from the deprecated `llm_config` table or from `settings.openai_api_key` after this change is deployed.

A helper module `services/ai_step_resolver.py` SHALL expose a function that, given a `step_key`, returns a dataclass with the resolved `base_url`, `api_key`, `model`, and parsed `extra_config`. The resolver SHALL raise an explicit error if the step row exists but its `api_key_id` is null when the step_type requires it (chat / embedding / whisper-api), so callers see a clear configuration error rather than a downstream 401 from the provider.

#### Scenario: RAG answer call uses ai_steps.answer

- **GIVEN** `ai_steps.answer` row has `base_url="https://hnd1.aihub.zeabur.ai/v1"`, `model="gpt-4o"`, `api_key_id=K`
- **AND** `api_keys.K` has `api_key="sk-hub-..."`
- **WHEN** a user submits a query through `/query`
- **THEN** the OpenAI client used inside `rag.py` SHALL be constructed with `base_url="https://hnd1.aihub.zeabur.ai/v1"` and `api_key="sk-hub-..."`, and its `chat.completions.create()` SHALL be called with `model="gpt-4o"`

#### Scenario: Embedding call uses ai_steps.embedding

- **GIVEN** `ai_steps.embedding` row has `base_url="https://api.openai.com/v1"`, `model="text-embedding-3-small"`, `api_key_id=K2` referencing an OpenAI key
- **WHEN** the embedding service produces a vector
- **THEN** the OpenAI client SHALL use that base_url + key + model, NOT `settings.openai_api_key`

#### Scenario: Transcription provider chosen by extra_config.provider

- **GIVEN** `ai_steps.transcription` has `step_type="whisper"`, `extra_config={"provider": "faster-whisper", "model_dir": "/data/models"}`, `api_key_id=null`
- **WHEN** the transcription factory is asked for a provider instance
- **THEN** the factory SHALL return a `FasterWhisperProvider` configured with `model_dir="/data/models"` (read from `extra_config`), and SHALL NOT read `settings.faster_whisper_model_dir`

#### Scenario: Resolver fails fast for missing api_key on chat step

- **GIVEN** `ai_steps.summary` row exists but `api_key_id IS NULL`
- **WHEN** any caller invokes `resolver.get("summary")`
- **THEN** the resolver SHALL raise `AiStepNotConfiguredError("summary requires api_key_id")` synchronously, before any HTTP call is attempted


<!-- @trace
source: admin-llm-step-config
updated: 2026-05-03
code:
  - backend/alembic/versions/m1b2c3d4e5f6_drop_llm_config.py
  - backend/app/services/transcription/openai_provider.py
  - src/Shared.jsx
  - backend/app/main.py
  - backend/app/services/embedding.py
  - backend/app/services/transcription/factory.py
  - docs/research/competitive-analysis.md
  - backend/app/schemas/api_key.py
  - backend/app/api/admin/api_keys.py
  - backend/app/schemas/ai_step.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/core/config.py
  - aisteps-tab.png
  - backend/app/core/bootstrap.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - backend/app/api/query.py
  - backend/app/models/__init__.py
  - backend/app/api/admin/__init__.py
  - backend/app/schemas/admin.py
  - backend/alembic/versions/l0a1b2c3d4e5_add_api_keys_and_ai_steps.py
  - backend/app/services/ai_step_resolver.py
  - index.html
  - src/AdminPage.jsx
  - docs/research/competitive-feature-plan.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/llm_config.py
  - backend/app/api/admin.py
  - backend/app/workers/tasks.py
  - backend/app/models/ai_step.py
  - backend/app/services/llm_config.py
  - src/releaseLog.jsx
  - backend/app/models/api_key.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/roadmap.md
tests:
  - backend/tests/test_ai_step_resolver.py
  - backend/tests/test_admin_ai_steps.py
  - backend/tests/test_admin_llm_step_migration.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_admin_api_keys.py
  - backend/tests/test_provider_label.py
-->

---
### Requirement: Migration imports legacy llm_config and openai_api_key env

The migration that creates `api_keys` and `ai_steps` SHALL import existing data so the application keeps working without manual admin input post-deploy:

1. If `llm_config` row with `id=1` exists, INSERT one `api_keys` row per distinct `(answer_api_key, rewrite_api_key)` value (deduplicated; provider inferred from `answer_base_url` / `rewrite_base_url` host: hostnames containing `aihub.zeabur` SHALL map to `provider="zeabur-aihub"`, hostnames containing `api.openai.com` SHALL map to `provider="openai"`, all others SHALL map to `provider="unknown"` with a `label="legacy-import"`). UPDATE the pre-inserted `ai_steps.answer` / `ai_steps.rewrite` rows with the corresponding `base_url`, `model`, `api_key_id`.
2. If `settings.openai_api_key` env exists at migration runtime AND no `api_keys` row already holds this exact key value, INSERT one `api_keys` row with `provider="openai", label="legacy-env-import"`. UPDATE `ai_steps.embedding` to point `api_key_id` at this row, set `base_url="https://api.openai.com/v1"`, `model="text-embedding-3-small"` (current default).
3. UPDATE `ai_steps.transcription`'s `extra_config` to `{"provider": "<env-provider-name>"}` plus any provider-specific key (e.g. `model_dir` for faster-whisper) read from current settings; if provider is `openai`, set `api_key_id` to the OpenAI key inserted above and `base_url="https://api.openai.com/v1"`, `model="whisper-1"`.
4. The `summary` step row SHALL be left with `api_key_id=null`, `base_url=""`, `model=""`. It is the admin's responsibility to fill these in before the `episode-ai-summary` change is deployed.

The `llm_config` table SHALL NOT be dropped in this migration. A separate later migration (Rev B) SHALL drop it after the application code stops referencing it.

#### Scenario: Migration with existing llm_config and env

- **GIVEN** `llm_config.id=1` has `answer_base_url="https://hnd1.aihub.zeabur.ai/v1", answer_api_key="K_HUB", answer_model="gpt-4o", rewrite_base_url="https://hnd1.aihub.zeabur.ai/v1", rewrite_api_key="K_HUB", rewrite_model="gpt-4o-mini"`
- **AND** env `OPENAI_API_KEY="K_OAI"`
- **WHEN** the migration runs
- **THEN** `api_keys` SHALL contain at least two rows: one with `provider="zeabur-aihub", api_key="K_HUB"` and one with `provider="openai", api_key="K_OAI"`
- **AND** `ai_steps.answer` SHALL have `base_url="https://hnd1.aihub.zeabur.ai/v1", model="gpt-4o", api_key_id` pointing to the Hub row
- **AND** `ai_steps.embedding` SHALL have `api_key_id` pointing to the OpenAI row
- **AND** `ai_steps.summary` SHALL have `api_key_id=null, base_url="", model=""`

#### Scenario: Rev B drops llm_config after app code is deployed

- **GIVEN** Rev A has run and the new application code is live
- **WHEN** Rev B is applied
- **THEN** the `llm_config` table SHALL be dropped, and downgrade SHALL recreate the table with its original schema (best-effort; data is not restored)


<!-- @trace
source: admin-llm-step-config
updated: 2026-05-03
code:
  - backend/alembic/versions/m1b2c3d4e5f6_drop_llm_config.py
  - backend/app/services/transcription/openai_provider.py
  - src/Shared.jsx
  - backend/app/main.py
  - backend/app/services/embedding.py
  - backend/app/services/transcription/factory.py
  - docs/research/competitive-analysis.md
  - backend/app/schemas/api_key.py
  - backend/app/api/admin/api_keys.py
  - backend/app/schemas/ai_step.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/core/config.py
  - aisteps-tab.png
  - backend/app/core/bootstrap.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - backend/app/api/query.py
  - backend/app/models/__init__.py
  - backend/app/api/admin/__init__.py
  - backend/app/schemas/admin.py
  - backend/alembic/versions/l0a1b2c3d4e5_add_api_keys_and_ai_steps.py
  - backend/app/services/ai_step_resolver.py
  - index.html
  - src/AdminPage.jsx
  - docs/research/competitive-feature-plan.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/llm_config.py
  - backend/app/api/admin.py
  - backend/app/workers/tasks.py
  - backend/app/models/ai_step.py
  - backend/app/services/llm_config.py
  - src/releaseLog.jsx
  - backend/app/models/api_key.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/roadmap.md
tests:
  - backend/tests/test_ai_step_resolver.py
  - backend/tests/test_admin_ai_steps.py
  - backend/tests/test_admin_llm_step_migration.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_admin_api_keys.py
  - backend/tests/test_provider_label.py
-->

---
### Requirement: Admin UI presents api_keys and ai_steps as two separate tabs

The admin frontend SHALL provide two tabs reachable from the admin sidebar:

1. **API 金鑰管理 / API Keys** (`admin-api`): list all `api_keys` rows, each row showing `provider` colour-coded badge, `label`, masked `api_key` (last 4 chars + `••••`), `created_at`. Provide Add / Edit / Delete buttons. Add / Edit form SHALL have inputs for `provider` (dropdown with free-text allowed; default options `openai / anthropic / google / zeabur-aihub`), `label`, `api_key`. The form SHALL hit real backend endpoints (no mock data SHALL remain).
2. **AI 處理步驟 / AI Steps** (`admin-llm` route, component renamed `AiStepsTab`): list the five step rows in fixed order (`answer`, `rewrite`, `summary`, `embedding`, `transcription`). Each step renders a sub-form whose fields depend on `step_type`:
   - `chat`: `base_url` (free text + dropdown of common values), `model` (free text + dropdown of common values for the chosen provider), `api_key_id` (dropdown of `api_keys` rows).
   - `embedding`: same as chat but `api_key_id` dropdown SHALL be filtered to `provider="openai"` rows only.
   - `whisper`: `extra_config.provider` dropdown (`openai` / `faster-whisper`); when `openai` selected, also show `base_url`, `model`, `api_key_id`; when `faster-whisper` selected, show `model_dir` and `model` (e.g. `large-v3`), and HIDE `api_key_id`.

The AI Steps tab SHALL NOT show an api_key text input anywhere — the api_key is referenced via dropdown.

#### Scenario: Embedding step form filters api_key dropdown

- **GIVEN** the user is on the AI Steps tab
- **WHEN** the embedding step form's api_key dropdown is opened
- **THEN** only entries whose `provider == "openai"` SHALL be listed

#### Scenario: Whisper step form switches fields by provider

- **GIVEN** the transcription step is showing with `extra_config.provider = "openai"`
- **WHEN** the user switches the provider dropdown to `faster-whisper`
- **THEN** the form SHALL hide `api_key_id`, hide `base_url`, and show `model_dir` input

#### Scenario: Embedding model change warning

- **WHEN** the user edits the embedding step's `model` field to a value different from its current saved value
- **THEN** the form SHALL display an inline warning: "改 model 會讓既有 vector 失效，需要 reindex" (zh) / "Changing the model invalidates existing vectors; reindex required" (en) before the user clicks Save

<!-- @trace
source: admin-llm-step-config
updated: 2026-05-03
code:
  - backend/alembic/versions/m1b2c3d4e5f6_drop_llm_config.py
  - backend/app/services/transcription/openai_provider.py
  - src/Shared.jsx
  - backend/app/main.py
  - backend/app/services/embedding.py
  - backend/app/services/transcription/factory.py
  - docs/research/competitive-analysis.md
  - backend/app/schemas/api_key.py
  - backend/app/api/admin/api_keys.py
  - backend/app/schemas/ai_step.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/core/config.py
  - aisteps-tab.png
  - backend/app/core/bootstrap.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - backend/app/api/query.py
  - backend/app/models/__init__.py
  - backend/app/api/admin/__init__.py
  - backend/app/schemas/admin.py
  - backend/alembic/versions/l0a1b2c3d4e5_add_api_keys_and_ai_steps.py
  - backend/app/services/ai_step_resolver.py
  - index.html
  - src/AdminPage.jsx
  - docs/research/competitive-feature-plan.md
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/api/admin/ai_steps.py
  - backend/app/models/llm_config.py
  - backend/app/api/admin.py
  - backend/app/workers/tasks.py
  - backend/app/models/ai_step.py
  - backend/app/services/llm_config.py
  - src/releaseLog.jsx
  - backend/app/models/api_key.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/roadmap.md
tests:
  - backend/tests/test_ai_step_resolver.py
  - backend/tests/test_admin_ai_steps.py
  - backend/tests/test_admin_llm_step_migration.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_admin_api_keys.py
  - backend/tests/test_provider_label.py
-->