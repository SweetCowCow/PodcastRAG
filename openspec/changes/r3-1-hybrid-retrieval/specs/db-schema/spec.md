## ADDED Requirements

### Requirement: transcript_chunks tsvector column

The `transcript_chunks` table SHALL contain a `text_tsvector` column of type `tsvector` (nullable, populated by application code after jieba tokenisation), and a GIN index `ix_chunks_text_tsvector` over that column. The column SHALL NOT be a `GENERATED` column because PostgreSQL has no built-in Chinese tokeniser and the value must be produced application-side using jieba + the custom dictionary.

#### Scenario: Column and index present after migration

- **WHEN** the `r3.1-hybrid-retrieval` Alembic migration runs
- **THEN** `transcript_chunks` SHALL have a column `text_tsvector tsvector NULL`
- **AND** an index named `ix_chunks_text_tsvector` of type GIN SHALL exist on that column

#### Scenario: tsvector populated during chunk write

- **WHEN** the chunking pipeline writes a `transcript_chunks` row
- **THEN** the row's `text_tsvector` SHALL be set to `to_tsvector('simple', '<jieba tokens joined by spaces>')` evaluated on the application side
- **AND** rows already in the table from prior runs MAY have `NULL` until the rebuild script populates them

### Requirement: tokenizer_custom_terms table

The database SHALL contain a `tokenizer_custom_terms` table storing user-curated entity terms used to seed jieba's tokeniser. Each row SHALL have:

- `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
- `term VARCHAR(100) NOT NULL UNIQUE`
- `weight INTEGER NOT NULL DEFAULT 100` (passed to `jieba.add_word(term, weight)`)
- `source VARCHAR(50) NOT NULL DEFAULT 'manual'` (e.g. `manual`, `seed_script`)
- `created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`
- `created_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL`

#### Scenario: Insert with default columns

- **WHEN** the application inserts a row with only `term='迪拉胖'`
- **THEN** the row SHALL be persisted with `weight=100`, `source='manual'`, and the current timestamp

#### Scenario: Duplicate term rejected by uniqueness

- **GIVEN** a row exists with `term='台通'`
- **WHEN** another insert with `term='台通'` is attempted
- **THEN** the insert SHALL fail with a unique-constraint error and the original row SHALL remain unchanged

### Requirement: episode_description_chunks table

The database SHALL contain an `episode_description_chunks` table storing one row per episode with non-empty cleaned description, mirroring the search-relevant fields of `transcript_chunks`. Each row SHALL have:

- `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
- `episode_id UUID NOT NULL UNIQUE REFERENCES episodes(id) ON DELETE CASCADE`
- `text TEXT NOT NULL` (HTML-stripped + boilerplate-stripped description)
- `text_tsvector tsvector NULL`
- `embedding vector(1536) NULL`
- `created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`
- `updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`

The table SHALL have a GIN index `ix_desc_text_tsvector` on `text_tsvector` and an `ivfflat` index `ix_desc_embedding` on `embedding` using `vector_cosine_ops` with `lists=100`.

#### Scenario: One row per episode

- **WHEN** an episode with non-empty description is indexed
- **THEN** exactly one row SHALL exist in `episode_description_chunks` for that `episode_id`
- **AND** subsequent re-indexing of the same episode SHALL UPDATE the existing row, not insert a duplicate

#### Scenario: Episode delete cascades

- **WHEN** a row in `episodes` is deleted
- **THEN** any matching `episode_description_chunks` rows SHALL be deleted automatically by the foreign-key cascade

#### Scenario: Indices present after migration

- **WHEN** the migration runs
- **THEN** indices `ix_desc_text_tsvector` (GIN) and `ix_desc_embedding` (ivfflat, lists=100, vector_cosine_ops) SHALL exist on the new table
