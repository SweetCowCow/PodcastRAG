## ADDED Requirements

### Requirement: qa_feedback table

The database SHALL contain a `qa_feedback` table storing thumbs vote and optional comment per AI-answer interaction.

Columns:
- `id` UUID PRIMARY KEY DEFAULT gen_random_uuid()
- `query_id` VARCHAR(64) NOT NULL — opaque id assigned by the backend per RAG query response
- `user_id` UUID NOT NULL REFERENCES `users(id)` ON DELETE CASCADE
- `vote` VARCHAR(8) NOT NULL CHECK (`vote` IN ('up', 'down'))
- `comment` TEXT NULL
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()

Indexes:
- `ix_qa_feedback_query_user_created` on `(query_id, user_id, created_at DESC)` to support "latest vote per (user, query)" reads

The table SHALL be append-only: votes are inserted as new rows; existing rows SHALL NOT be updated or deleted on re-vote.

#### Scenario: Migration creates the table

- **WHEN** the Alembic migration runs
- **THEN** `qa_feedback` SHALL exist with all listed columns and the index `ix_qa_feedback_query_user_created`

#### Scenario: User deletion cascades

- **GIVEN** a user with 5 qa_feedback rows
- **WHEN** the user row is deleted
- **THEN** all 5 qa_feedback rows SHALL be removed by the cascade

#### Scenario: Invalid vote rejected by CHECK constraint

- **WHEN** an insert attempts `vote='maybe'`
- **THEN** Postgres SHALL raise a CHECK constraint violation

### Requirement: events table

The database SHALL contain an `events` table for general-purpose client-side event ingestion.

Columns:
- `id` UUID PRIMARY KEY DEFAULT gen_random_uuid()
- `event_type` VARCHAR(32) NOT NULL — discriminator (initial allowed value: `'citation_click'`)
- `event_payload` JSONB NOT NULL — type-specific payload, validated at the API layer
- `user_id` UUID NULL REFERENCES `users(id)` ON DELETE SET NULL — populated when the request carries a valid session
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()

Indexes:
- `ix_events_type_created` on `(event_type, created_at DESC)`

The table schema SHALL allow future event types without schema migration; payload validation SHALL happen at the API layer (Pydantic schemas keyed by `event_type`).

#### Scenario: Migration creates the table

- **WHEN** the Alembic migration runs
- **THEN** `events` SHALL exist with all listed columns and the index `ix_events_type_created`

#### Scenario: Event row persists arbitrary payload as JSONB

- **WHEN** a row is inserted with `event_payload = {"query_id": "q-1", "chunk_id": "c-2", "position": 0}`
- **THEN** the row SHALL be readable back with the same JSON structure

#### Scenario: Anonymous event has NULL user_id

- **WHEN** the API inserts an event without a session-resolved user
- **THEN** the row SHALL have `user_id IS NULL`

#### Scenario: User deletion sets event user_id to NULL (preserves event row)

- **GIVEN** a user with 3 events rows
- **WHEN** the user is deleted
- **THEN** the events rows SHALL still exist
- **AND** their `user_id` SHALL be NULL
