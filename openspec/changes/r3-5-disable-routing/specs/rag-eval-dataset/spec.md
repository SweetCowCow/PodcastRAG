## MODIFIED Requirements

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

## ADDED Requirements

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
