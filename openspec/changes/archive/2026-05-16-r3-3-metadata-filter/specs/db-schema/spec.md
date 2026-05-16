## ADDED Requirements

### Requirement: episodes.guests JSONB column

The `episodes` table SHALL include a `guests` JSONB column storing a list of guest name strings, with default value `'[]'::jsonb`, NOT NULL.

#### Scenario: Migration adds column with default

- **WHEN** alembic migration `r33_episodes_guests_and_title_tsvector` runs against an existing database
- **THEN** the `episodes` table MUST gain a `guests` column of type `jsonb`, default `'[]'::jsonb`, NOT NULL
- **AND** all existing rows MUST have `guests = '[]'::jsonb` after migration

#### Scenario: GIN index supports containment query

- **WHEN** the migration runs
- **THEN** an index `idx_episodes_guests` MUST be created as `GIN (guests jsonb_path_ops)` to support efficient `@>` containment queries

### Requirement: episodes.title_tsvector generated column

The `episodes` table SHALL include a `title_tsvector` generated column whose value is `to_tsvector('simple', tokenize_for_tsvector(title))` using the jieba tokenizer (see tokenizer-dictionary capability), maintained automatically by the database.

#### Scenario: Generated column populated on existing rows

- **WHEN** alembic migration runs against an existing database with ~400 episode rows
- **THEN** the `episodes` table MUST gain a `title_tsvector` column populated for every existing row by the database engine

#### Scenario: Generated column updates on title change

- **WHEN** an episode's `title` is UPDATEd
- **THEN** the `title_tsvector` value MUST automatically reflect the new tokenised title without an explicit UPDATE statement

#### Scenario: GIN index supports tsquery match

- **WHEN** the migration runs
- **THEN** an index `idx_episodes_title_tsv` MUST be created as `GIN (title_tsvector)` to support `@@` tsquery matches
