# rag-eval-dataset Specification

## Purpose

TBD - created by archiving change 'r1-eval-framework'. Update Purpose after archive.

## Requirements

### Requirement: Golden set is stored per-show as JSON under backend/eval/datasets

The repository SHALL contain golden-set JSON files under `backend/eval/datasets/{show_slug}.json`, one file per show. Each file SHALL conform to a documented schema at `backend/eval/datasets/_schema.json`. The `show_slug` SHALL be lowercase, hyphen-separated, ASCII-only (e.g., `this-not-that-cool`); a non-ASCII display title SHALL NOT be used as the file name even though the show title is Chinese.

#### Scenario: First show golden set committed

- **GIVEN** the show "這又沒有很屌" exists in the database
- **WHEN** golden set v1 is delivered
- **THEN** `backend/eval/datasets/this-not-that-cool.json` SHALL exist
- **AND** the file SHALL validate against `_schema.json`
- **AND** the file's `show_slug` field SHALL equal `this-not-that-cool`

#### Scenario: Schema requires version, show_id, items

- **WHEN** a tool reads `_schema.json`
- **THEN** the schema SHALL declare these required top-level fields: `show_slug`, `show_id`, `version`, `created_at`, `items`

---
### Requirement: Each golden set item has type, ground-truth chunks, and sentinel flag

Every item in `items[]` SHALL have these fields:
- `id`: short stable identifier (e.g., `tntc-001`)
- `type`: one of `fact` | `comprehension` | `cross-episode` | `negative` | `code-switch`
- `question`: the prompt to ask the RAG endpoint (1–500 chars)
- `expected_answer_keywords`: list of 1–10 short Chinese/English keywords expected to appear in a correct answer (used for the lightweight keyword overlap signal; MAY be empty for `negative` type)
- `ground_truth_chunk_ids`: list of chunk identifiers in the canonical `ep:<episode_uuid>@<start_time_seconds>` format (MAY be empty for `negative` type)
- `sentinel`: boolean — true for the 10 hand-crafted "must never regress" items
- `source_episode_id`: UUID of the primary episode the item is anchored to (used by the skill to track diversity coverage)

#### Scenario: Fact item has at least one ground-truth chunk

- **GIVEN** an item with `type: "fact"`
- **WHEN** the dataset is validated
- **THEN** `ground_truth_chunk_ids` SHALL contain at least 1 entry

#### Scenario: Negative item has no ground-truth chunks

- **GIVEN** an item with `type: "negative"` (e.g., asking about a topic not covered)
- **WHEN** the dataset is validated
- **THEN** `ground_truth_chunk_ids` MAY be an empty list
- **AND** `expected_answer_keywords` MAY be an empty list

#### Scenario: chunk_id format matches the RAG citation format

- **GIVEN** an item references chunk `ep:abc-123@21.05`
- **WHEN** the same chunk is returned by `/shows/{id}/query` as a citation
- **THEN** the citation's derived id (computed as `ep:{episode_id}@{start_time:.2f}`) SHALL equal `ep:abc-123@21.05`

---
### Requirement: Initial golden set covers 50 items across 5 types

The first delivered golden set (`this-not-that-cool.json`) SHALL contain exactly 50 items distributed as: `fact` 19, `comprehension` 12, `cross-episode` 10, `negative` 6, `code-switch` 3. Of these, exactly 10 items SHALL have `sentinel: true`, distributed across types as: `fact` 3, `comprehension` 2, `cross-episode` 2, `negative` 2, `code-switch` 1.

#### Scenario: Counts are enforced at validation time

- **WHEN** `backend/eval/datasets/this-not-that-cool.json` is loaded
- **THEN** the type histogram SHALL be `{fact: 19, comprehension: 12, cross-episode: 10, negative: 6, code-switch: 3}`
- **AND** the count of items with `sentinel: true` SHALL be exactly 10
