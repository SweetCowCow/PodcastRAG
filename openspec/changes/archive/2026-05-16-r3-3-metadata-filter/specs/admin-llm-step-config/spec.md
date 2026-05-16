## MODIFIED Requirements

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
