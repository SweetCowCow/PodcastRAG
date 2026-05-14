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
- `eval_mode`: one of `chunk_id` | `open_set_lenient` | `enumeration`. This field SHALL be present on every item with no default — the JSON Schema MUST mark `eval_mode` as required so missing values fail validation rather than fall back to an implicit default.
- `question`: the prompt to ask the RAG endpoint (1–500 chars)
- `expected_answer_keywords`: list of 1–10 short Chinese/English keywords expected to appear in a correct answer (used for the lightweight keyword overlap signal; MAY be empty for `negative` type)
- `ground_truth_chunk_ids`: list of chunk identifiers in the canonical `ep:<episode_uuid>@<start_time_seconds>` format. SHALL be present whenever `eval_mode` is `chunk_id` or `open_set_lenient` (MAY be empty for `negative` items under `chunk_id`).
- `expected_episode_ids`: list of episode UUIDs. SHALL be present and non-empty whenever `eval_mode` is `enumeration`. MUST be absent or empty for other modes.
- `sentinel`: boolean — true for the 10 hand-crafted "must never regress" items
- `source_episode_id`: UUID of the primary episode the item is anchored to (used by the skill to track diversity coverage)

The `eval_mode` field declares which retrieval-scoring contract the eval runner SHALL apply to this item:
- `chunk_id`: legacy behavior — runner matches retrieved chunk identifiers against `ground_truth_chunk_ids` (this is the only mode that preserves the empty-ground-truth → excluded-from-mean negative-item behavior).
- `open_set_lenient`: runner credits the item if any retrieved chunk hits any anchor in `ground_truth_chunk_ids`, treating recall as 1.0/0.0 rather than fractional.
- `enumeration`: runner ignores `ground_truth_chunk_ids` and instead computes episode-set recall against `expected_episode_ids`.

`type` and `eval_mode` are orthogonal. A `cross-episode` item MAY use any of the three modes; the type captures cognitive classification for humans while `eval_mode` is the machine-readable scoring contract.

#### Scenario: Fact item has at least one ground-truth chunk

- **GIVEN** an item with `type: "fact"` and `eval_mode: "chunk_id"`
- **WHEN** the dataset is validated
- **THEN** `ground_truth_chunk_ids` SHALL contain at least 1 entry

#### Scenario: Negative item has no ground-truth chunks

- **GIVEN** an item with `type: "negative"` and `eval_mode: "chunk_id"` (e.g., asking about a topic not covered)
- **WHEN** the dataset is validated
- **THEN** `ground_truth_chunk_ids` MAY be an empty list
- **AND** `expected_answer_keywords` MAY be an empty list

#### Scenario: chunk_id format matches the RAG citation format

- **GIVEN** an item references chunk `ep:abc-123@21.05`
- **WHEN** the same chunk is returned by `/shows/{id}/query` as a citation
- **THEN** the citation's derived id (computed as `ep:{episode_id}@{start_time:.2f}`) SHALL equal `ep:abc-123@21.05`

#### Scenario: Missing eval_mode rejected at validation

- **GIVEN** an item lacking the `eval_mode` field
- **WHEN** the dataset is validated against `_schema.json`
- **THEN** validation SHALL fail with an error naming `eval_mode` as a missing required field

#### Scenario: Enumeration item requires non-empty expected_episode_ids

- **GIVEN** an item with `eval_mode: "enumeration"` and `expected_episode_ids: []`
- **WHEN** the dataset is validated against `_schema.json`
- **THEN** validation SHALL fail with an error indicating `expected_episode_ids` MUST contain at least one entry for enumeration mode

##### Example: enumeration item shape

- **GIVEN** a cross-episode listing question "節目裡有哪些集是歌單？"
- **WHEN** the item is added to the golden set
- **THEN** the item SHALL set `type: "cross-episode"`, `eval_mode: "enumeration"`, `ground_truth_chunk_ids: []`, and `expected_episode_ids: [<25 episode UUIDs>]`

#### Scenario: Non-enumeration item MUST NOT carry expected_episode_ids content

- **GIVEN** an item with `eval_mode: "chunk_id"` or `eval_mode: "open_set_lenient"`
- **WHEN** the dataset is validated
- **THEN** `expected_episode_ids` SHALL be absent or an empty list (validator MUST reject non-empty values to prevent silent mode confusion)

---
### Requirement: Initial golden set covers 50 items across 5 types

The first delivered golden set (`this-not-that-cool.json`) SHALL contain exactly 10 hand-crafted human-curated items distributed as: `fact` 3, `comprehension` 2, `cross-episode` 2, `negative` 2, `code-switch` 1. All 10 items SHALL have `sentinel: true`. The dataset MAY contain additional non-sentinel items beyond this set; non-sentinel items SHALL NOT be created by purely automated LLM generation without human review (see `Requirement: LLM-auto-generated items SHALL pass human review before inclusion`).

Historical context: a prior revision specified 48 items including 38 LLM-auto-generated items (e.g., `thisno-core-com-*`, `thisno-core-cro-*`, `thisno-core-fact-*`). The 2026-05-13 audit established that the LLM-auto items had a verified bad-question rate ≥ 75% (single-keyword-triggered deep questions, anchor not aligned with question semantics, cross-episode anchors with episodes unrelated to the question). All 36 `thisno-core-*` items were removed; `q01-q10` (the 10 hand-crafted sentinel items) remain.

#### Scenario: Counts are enforced at validation time

- **WHEN** `backend/eval/datasets/this-not-that-cool.json` is loaded
- **THEN** items with `sentinel: true` SHALL number exactly 10
- **AND** the sentinel histogram SHALL be `{fact: 3, comprehension: 2, cross-episode: 2, negative: 2, code-switch: 1}`
- **AND** the total `items` count SHALL be at least 10

#### Scenario: Removed LLM-auto items SHALL not reappear

- **GIVEN** the audited dataset omits all `thisno-core-*` ids
- **WHEN** any tool reloads or rewrites `this-not-that-cool.json`
- **THEN** no item with `id` matching the pattern `^thisno-core-` SHALL be re-introduced unless the item has separately passed human review per the LLM-auto-generated review requirement

---
### Requirement: LLM-auto-generated items SHALL pass human review before inclusion

Any candidate golden-set item produced by `backend/eval/scripts/build_golden_set.py` or any equivalent LLM-generation tool SHALL be written to a staging file (e.g., `backend/eval/datasets/_pending_review.json`) and SHALL NOT be merged into `backend/eval/datasets/{show_slug}.json` until a human reviewer has confirmed that the `question`, `expected_answer_keywords`, and each entry in `ground_truth_chunk_ids` semantically align with content in the referenced `source_episode_id` chunks. The merging tool SHALL refuse to copy any candidate from staging to the main dataset unless the candidate carries a `reviewed_by` field bearing a non-empty reviewer identifier and a `reviewed_at` ISO8601 timestamp.

#### Scenario: Staged candidate without review SHALL NOT be merged

- **GIVEN** a candidate item exists in `backend/eval/datasets/_pending_review.json` with no `reviewed_by` field
- **WHEN** the merging tool runs
- **THEN** the tool SHALL leave the candidate in staging
- **AND** the tool SHALL emit a warning naming the unreviewed candidate id

#### Scenario: Reviewed candidate is merged into main dataset

- **GIVEN** a staged candidate carrying `reviewed_by: "<reviewer>"` and `reviewed_at: "<iso8601-timestamp>"`
- **WHEN** the merging tool runs
- **THEN** the candidate SHALL be appended to `backend/eval/datasets/{show_slug}.json`
- **AND** the candidate SHALL be removed from staging
- **AND** the candidate's `id` SHALL NOT clash with any existing item id

#### Scenario: Pure LLM batch insert is rejected at validation

- **WHEN** any process attempts to write items into the main dataset whose ids match a generator-prefixed pattern (e.g., `thisno-core-*`) without corresponding `reviewed_by`/`reviewed_at` metadata anywhere in audit history
- **THEN** the operation SHALL fail validation
- **AND** the dataset file on disk SHALL NOT be modified
