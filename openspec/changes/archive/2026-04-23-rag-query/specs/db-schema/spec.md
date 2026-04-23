## ADDED Requirements

### Requirement: transcript_chunks table for RAG retrieval

The database SHALL contain a `transcript_chunks` table storing chunk-level text groupings with 1536-dimensional embeddings, serving as the vector search unit for RAG queries.

#### Scenario: Chunk record created

- **WHEN** a chunk is inserted with a valid `transcript_id`
- **THEN** the record SHALL be persisted with UUID primary key, `transcript_id` foreign key with `ON DELETE CASCADE`, `chunk_index` (non-negative integer unique within a transcript), `start_time` (float seconds), `end_time` (float seconds greater than `start_time`), `text` (non-empty), `embedding` (nullable `vector(1536)`), `segment_ids` (non-empty `uuid[]`), and `created_at` (timestamptz default now)

#### Scenario: Cosine similarity search via ivfflat index

- **WHEN** a cosine similarity query using the `<=>` operator is executed against `transcript_chunks.embedding`
- **THEN** the query planner SHALL use the ivfflat index (`vector_cosine_ops`, `lists=100`) when the query shape matches, and results SHALL be ordered by ascending distance

#### Scenario: Cascaded deletion on transcript removal

- **WHEN** a row in `transcripts` is deleted
- **THEN** all `transcript_chunks` rows whose `transcript_id` matches SHALL be deleted by the database cascade

---

### Requirement: llm_config singleton table

The database SHALL contain a `llm_config` table constrained to exactly one row (`id=1`), storing LLM gateway settings for the RAG answer and rewrite models.

#### Scenario: Singleton constraint enforced

- **WHEN** an application attempts to insert a second row into `llm_config` with a different `id`
- **THEN** the insert SHALL fail due to the check constraint `id = 1`

#### Scenario: Columns persisted

- **WHEN** the `llm_config` row is read
- **THEN** it SHALL contain non-null `answer_base_url` (varchar 500), `answer_api_key` (text), `answer_model` (varchar 200), `rewrite_base_url` (varchar 500), `rewrite_api_key` (text), `rewrite_model` (varchar 200), and `updated_at` (timestamptz default now)

#### Scenario: Seed row present after migration

- **WHEN** the migration that creates `llm_config` completes
- **THEN** a single row SHALL exist with `id=1`, `answer_base_url=rewrite_base_url="https://hnd1.aihub.zeabur.ai/v1"`, `answer_model="gpt-4o"`, `rewrite_model="gpt-4o-mini"`, and empty-string API keys

## MODIFIED Requirements

### Requirement: transcript_segments table with pgvector

The database SHALL contain a `transcript_segments` table storing timed text segments produced by the transcription provider. Segments SHALL NOT store vector embeddings; embeddings are stored at the chunk level in `transcript_chunks`.

#### Scenario: Segment record created

- **WHEN** a segment is inserted with a valid `transcript_id`
- **THEN** the record SHALL be persisted with UUID primary key, `transcript_id` foreign key, `start_time` (float seconds), `end_time` (float seconds), `text` (non-empty), and `speaker` (nullable)

#### Scenario: No embedding column

- **WHEN** the schema of `transcript_segments` is inspected after this change is applied
- **THEN** the table SHALL NOT contain an `embedding` column

## ADDED Requirements

### Requirement: Alembic migration for RAG tables

The codebase SHALL contain an Alembic migration that creates `transcript_chunks` and `llm_config` tables, seeds the singleton `llm_config` row, drops the `embedding` column from `transcript_segments`, and creates the ivfflat index on `transcript_chunks.embedding`.

#### Scenario: Upgrade creates and drops expected schema

- **WHEN** `alembic upgrade head` runs starting from the previous revision
- **THEN** `transcript_chunks` and `llm_config` SHALL exist with the columns and constraints defined above, the ivfflat index SHALL exist, the `llm_config` seed row SHALL be present, and `transcript_segments.embedding` SHALL no longer exist

#### Scenario: Downgrade restores prior schema

- **WHEN** `alembic downgrade -1` runs from this revision
- **THEN** `transcript_chunks` and `llm_config` SHALL be dropped, and `transcript_segments.embedding vector(1536)` SHALL be restored (nullable, no data)
