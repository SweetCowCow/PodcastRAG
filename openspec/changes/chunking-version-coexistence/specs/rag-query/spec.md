## ADDED Requirements

### Requirement: Description chunks carry `chunking_version` and `chunk_index`

The `episode_description_chunks` table SHALL include a `chunking_version smallint NOT NULL DEFAULT 1` column and a `chunk_index smallint NOT NULL DEFAULT 0` column. All rows existing before this migration SHALL be backfilled to `(chunking_version=1, chunk_index=0)` by the column DEFAULT. Newer chunking strategies (re-chunked variants) SHALL be written as rows with `chunking_version >= 2`. The chunk model SHALL expose both fields via SQLAlchemy.

#### Scenario: Existing rows backfilled to v1

- **GIVEN** rows existed in `episode_description_chunks` before this change
- **WHEN** the migration `t8_chunking_version_description_chunks` runs `upgrade()`
- **THEN** every existing row SHALL have `chunking_version = 1` and `chunk_index = 0`
- **AND** the columns SHALL be `NOT NULL`

#### Scenario: New rows can be written at v2

- **GIVEN** the migration has been applied
- **WHEN** an indexer writes a row with `chunking_version=2, chunk_index=0`
- **THEN** the row SHALL be persisted without violating any constraint
- **AND** a query for the same `episode_id` SHALL return both the v1 row and the v2 row

### Requirement: Composite unique on `(episode_id, chunking_version, chunk_index)` replaces per-episode unique

The `episode_description_chunks` table SHALL NOT have a single-column `UNIQUE(episode_id)` constraint. It SHALL have a `UNIQUE(episode_id, chunking_version, chunk_index)` constraint named `uq_desc_chunk_episode_version_index`. Two rows that share `episode_id` but differ in `chunking_version` or `chunk_index` SHALL be allowed to coexist.

#### Scenario: (episode, v1) and (episode, v2) coexist

- **GIVEN** a row `(episode_id=E, chunking_version=1, chunk_index=0)` already exists
- **WHEN** the indexer attempts to insert `(episode_id=E, chunking_version=2, chunk_index=0)`
- **THEN** the insert SHALL succeed

#### Scenario: Duplicate (episode, version, index) rejected

- **GIVEN** a row `(episode_id=E, chunking_version=2, chunk_index=5)` exists
- **WHEN** another insert with the same `(episode_id, chunking_version, chunk_index)` triplet runs
- **THEN** the database SHALL trigger the UPSERT `on_conflict_do_update` path on the new constraint
- **AND** no duplicate row SHALL be created

### Requirement: `retrieve_hybrid` pools v1 and v2 description chunks together

The description-side hybrid retrieval SQL (`_DESC_RRF_SQL` and `_DESC_SEMANTIC_ONLY_SQL` in `backend/app/services/rag.py`) SHALL NOT filter rows by `chunking_version`. The RRF pool SHALL contain all `chunking_version` variants for a given show, and ranking SHALL be decided solely by hybrid score. Callers SHALL NOT need to specify a `chunking_version` to retrieve results.

#### Scenario: Mixed v1+v2 pool ranks by score

- **GIVEN** a show has both v1 and v2 description chunks for some of its episodes
- **WHEN** `retrieve_descriptions()` is called for that show
- **THEN** the result hits MAY include both v1 and v2 chunks
- **AND** the ordering SHALL be by RRF score (or semantic distance when lexical pathway is empty), not by `chunking_version`

### Requirement: `ChunkHit` exposes `chunking_version` metadata

The `ChunkHit` dataclass SHALL include a `chunking_version: int` field with default value `1`. For description hits, the value SHALL reflect the row's `chunking_version` column. For transcript hits, the value SHALL remain the default `1` (transcript chunks are not versioned by this change).

#### Scenario: Description hit carries its row's version

- **GIVEN** a v2 description chunk wins RRF and enters top-K
- **WHEN** the API returns the corresponding `ChunkHit`
- **THEN** `chunk_hit.chunking_version` SHALL equal `2`

#### Scenario: Transcript hit defaults to v1

- **GIVEN** a transcript chunk enters top-K
- **WHEN** the API returns the corresponding `ChunkHit`
- **THEN** `chunk_hit.chunking_version` SHALL equal `1`
- **AND** no transcript-side query SHALL reference a `chunking_version` column

### Requirement: Dedup collapses same-episode multi-version description hits

When two description hits from the same `episode_id` but different `chunking_version` both enter the candidate pool, the dedup step SHALL retain only the hit with the higher RRF score (or lower semantic distance when in semantic-only fallback). The retained hit's `chunking_version` and `chunk_index` SHALL be preserved as metadata.

#### Scenario: v1 and v2 hits from same episode collapsed

- **GIVEN** a candidate pool contains `(episode=E, source=description, v=1, score=0.4)` and `(episode=E, source=description, v=2, score=0.6)`
- **WHEN** the dedup step runs
- **THEN** the output SHALL contain exactly one hit for episode E
- **AND** that hit SHALL have `chunking_version = 2`

### Requirement: Description indexer accepts `chunking_version` and `chunk_index` keyword parameters

`index_episode_description()` in `backend/app/services/description_indexer.py` SHALL accept keyword-only parameters `chunking_version: int = 1` and `chunk_index: int = 0`. The UPSERT SHALL key conflict resolution on the composite `(episode_id, chunking_version, chunk_index)` index. The empty-content delete pathway SHALL scope its `DELETE` to the same `(episode_id, chunking_version)` pair so it does not remove rows of another version.

#### Scenario: Default call writes v1 row

- **GIVEN** an existing caller invokes `index_episode_description(episode_id=E, text="...")` without naming `chunking_version`
- **WHEN** the indexer runs
- **THEN** the row written SHALL have `chunking_version=1, chunk_index=0`
- **AND** behaviour SHALL be identical to pre-change behaviour for v1-only data

#### Scenario: Versioned call writes v2 row without disturbing v1

- **GIVEN** a v1 row for episode E already exists
- **WHEN** `index_episode_description(episode_id=E, chunking_version=2, chunk_index=3, text="...")` is called
- **THEN** a new row `(E, 2, 3)` SHALL be inserted
- **AND** the existing `(E, 1, 0)` row SHALL remain unchanged

#### Scenario: Empty-content delete only scoped to one version

- **GIVEN** episode E has both v1 and v2 description rows
- **WHEN** `index_episode_description(episode_id=E, chunking_version=2, text="")` runs and triggers the delete-existing-empty pathway
- **THEN** only `(E, 2, *)` rows SHALL be deleted
- **AND** `(E, 1, *)` rows SHALL remain in place

### Requirement: `cleanup_v1_description_chunks.py` script is idempotent, dry-run-default, and v2-aware

The cleanup script at `backend/scripts/cleanup_v1_description_chunks.py` SHALL require `--show-id`. Without `--execute` it SHALL only print a plan (dry-run). It SHALL refuse to delete v1 rows for any show where at least one episode has no v2 chunk, unless `--force` is supplied. Deletion SHALL be scoped to `WHERE show_id = ? AND chunking_version = 1` and SHALL be per-episode transactional.

#### Scenario: Dry-run prints plan only

- **GIVEN** the script is invoked without `--execute`
- **WHEN** it finishes
- **THEN** no `DELETE` SHALL have been issued
- **AND** the printed plan SHALL include episode counts (`total`, `with_v2`, `missing_v2`)

#### Scenario: Refuses to delete when episodes lack v2 chunks

- **GIVEN** a show has 163 episodes but only 100 have v2 chunks
- **WHEN** the script runs with `--execute` but without `--force`
- **THEN** it SHALL exit with non-zero status
- **AND** no v1 rows SHALL be deleted

#### Scenario: --force overrides safeguard

- **GIVEN** the same condition as above
- **WHEN** the script runs with `--execute --force`
- **THEN** all v1 rows for the given show SHALL be deleted
- **AND** the operator SHALL accept the consequence that 63 episodes will have no description chunk afterwards

### Requirement: `chunking-status` admin endpoint reports v1/v2 breakdown

`GET /admin/chunking-status` SHALL be available to admin-authenticated requests and SHALL return, for every show, the episode total, the count of v1 description chunks, and the count of v2 description chunks. Non-admin callers SHALL receive `401` or `403`.

#### Scenario: Admin sees per-show breakdown

- **GIVEN** an admin-authenticated session
- **WHEN** the client requests `GET /admin/chunking-status`
- **THEN** the response SHALL contain one entry per show with `show_id`, `title`, `episode_total`, `v1_chunks`, `v2_chunks`
- **AND** for a show that has not yet been re-chunked, `v2_chunks` SHALL equal `0`

#### Scenario: Non-admin rejected

- **GIVEN** a non-admin or unauthenticated request
- **WHEN** it hits `GET /admin/chunking-status`
- **THEN** the response status SHALL be `401` or `403`
