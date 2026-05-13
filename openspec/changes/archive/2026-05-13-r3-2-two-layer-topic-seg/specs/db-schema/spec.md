## ADDED Requirements

### Requirement: transcript_segments topic_label column

The `transcript_segments` table SHALL contain a `topic_label VARCHAR(50) NULL` column populated by the topic-segmentation backfill (see `topic-segmentation` capability). The column SHALL accept any string (the application validates against the show's allowed label set; DB does not enforce this so per-show extensions can be added without schema migrations).

A btree index `ix_segments_topic_label` SHALL exist on `(topic_label)` to support future filter queries.

#### Scenario: Column nullable after migration

- **WHEN** the `r3.2-two-layer-topic-seg` migration runs against a populated DB
- **THEN** existing rows SHALL have `topic_label = NULL`
- **AND** new INSERTs without an explicit `topic_label` value SHALL succeed

#### Scenario: Index present

- **WHEN** the migration completes
- **THEN** index `ix_segments_topic_label` SHALL exist on column `topic_label` of `transcript_segments`

### Requirement: shows segment_categories column

The `shows` table SHALL contain a `segment_categories JSONB NOT NULL DEFAULT '[]'` column holding an array of `{name: str, desc: str}` objects representing per-show extension labels for the topic-segmentation pipeline. The application SHALL validate at admin / write time that each entry has both keys; the DB does not enforce structure.

#### Scenario: Default empty array

- **WHEN** an existing `shows` row is loaded after migration
- **THEN** `segment_categories` SHALL equal `[]`

#### Scenario: Custom categories survive UPSERT

- **GIVEN** an UPDATE sets `segment_categories = '[{"name":"playlist_segment","desc":"..."}]'` for one show
- **WHEN** that row is read back
- **THEN** the `segment_categories` value SHALL match exactly

### Requirement: tokenizer_custom_terms is_show_name flag

The `tokenizer_custom_terms` table SHALL contain an `is_show_name BOOLEAN NOT NULL DEFAULT false` column. Tokens with `is_show_name = true` SHALL be excluded from the `to_tsquery` lexical query string built by `_build_ts_query()` (see `tokenizer-dictionary` capability), but SHALL remain available to jieba for chunk-time tokenisation (so that show-name tokens still split correctly when the chunk text is tsvector-encoded).

#### Scenario: Default false after migration

- **WHEN** the migration completes
- **THEN** all existing rows in `tokenizer_custom_terms` SHALL have `is_show_name = false`

#### Scenario: Show-name flag persistable

- **GIVEN** an admin updates a row to `is_show_name = true`
- **WHEN** the row is read back
- **THEN** `is_show_name` SHALL equal `true`
