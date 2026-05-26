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

---
### Requirement: chat-rag golden dataset SHALL use v2 schema with must / acceptable tiered fields

The chat-rag golden dataset at `backend/eval/datasets/extended-multi-turn-40.json` (after this change) SHALL declare `schema_version: "2.0"` at the top level and SHALL conform to the v2 schema documented in `docs/eval-strategy.md`. The v2 schema SHALL support the following item-level fields:

- `id`, `design_type`, `source`, `question`, `is_multi_turn`, `audit_status`, `audit_notes` (basic identification)
- `expected_behavior`: one of `"answer" | "refuse" | "refusal_with_correction"`
- `expected_answer_summary`: natural-language description fed to LLM judge (replaces `expected_answer_keywords`)
- `expected_answer_aliases`: optional object mapping canonical names to ASR / synonym alias arrays (e.g., `{"電信局": ["公務人員"]}`)
- `expected_episode_uuids_must` / `expected_episode_uuids_acceptable`: two-tier episode set (must = required hit, acceptable = bonus)
- `expected_episode_numbers_must` / `expected_episode_numbers_acceptable`: human-readable EP-number mirror of UUID lists
- `expected_count`: optional integer for enumeration items, used by `count_consistency` grader
- `expected_top_n_episode_numbers`: optional ordered list for top-N order checks (e.g., DESC-sorted top-3)
- `expected_tool_calls_required` / `expected_tool_calls_acceptable`: tool name arrays
- `expected_tool_args`: object mapping tool name to argument constraints; argument constraints MAY use the form `{"<arg_name>_must_match_pattern": "<regex>"}` for regex match
- `ground_truth_chunk_ids_must` / `ground_truth_chunk_ids_either` / `ground_truth_chunk_ids_acceptable`: three-tier chunk-level GT (must = all required, either = any-one-in-group counts as hit for chunk-overlap handling, acceptable = bonus)
- `expected_must_contradict_check`: optional natural-language statement of what the answer MUST NOT contain (for reverse-question / contradiction detection)
- `turns`: array (only when `is_multi_turn: true`) containing per-turn variants of the above fields; each turn MAY additionally carry `carry_from` (string describing how this turn's answer derives from prior turn state) and `ordinal_resolution_check` (boolean flag triggering the ordinal grader)

The v2 schema SHALL be enforced by a JSON Schema validator at `backend/eval/datasets/_chat_rag_schema_v2.json`. Validation SHALL fail loudly when a field is malformed (e.g., `expected_episode_uuids_must` contains a non-UUID string).

#### Scenario: v2 dataset declares schema_version 2.0

- **GIVEN** the migrated `extended-multi-turn-40.json` after this change ships
- **WHEN** the file is loaded
- **THEN** the top-level `schema_version` field SHALL equal the string `"2.0"`
- **AND** the JSON Schema validator at `backend/eval/datasets/_chat_rag_schema_v2.json` SHALL accept the file with zero errors

#### Scenario: deep_dive item carries three-tier chunk-level GT for chunk overlap

- **GIVEN** the b14 deep_dive item targeting EP134
- **WHEN** the item is loaded
- **THEN** `ground_truth_chunk_ids_must` SHALL contain `"ep:c1d87278-7dba-4fb1-930d-c2bd3a3461d2@0.00"`
- **AND** `ground_truth_chunk_ids_either` SHALL contain BOTH `"ep:c1d87278-...@1790.18"` AND `"ep:c1d87278-...@1808.78"` so the grader credits the item when either chunk is retrieved (handling the 1-sentence cross-boundary overlap)

#### Scenario: leading_question_yes design_type is recognized

- **GIVEN** the b29 item migrated to v2 with `design_type: "leading_question_yes"`
- **WHEN** the dataset is validated
- **THEN** the validator SHALL accept the value
- **AND** the item SHALL carry `expected_behavior: "answer"` (the design type's defining property is that despite leading negative framing, the correct answer is YES)


<!-- @trace
source: eval-judge-incorporate-tool-grounding
updated: 2026-05-26
code:
  - backend/eval/prompts/chat_judge_v2.md
  - backend/eval/migrations/audit_overlay_2026_05_26.py
  - backend/eval/runner_v2_aggregate.py
  - backend/scripts/run_chat_agent_eval_v2.py
  - backend/eval/graders/answer_contradict_check.py
  - backend/eval/graders/ordinal_resolution.py
  - backend/eval/graders/chunk_recall_grouped.py
  - backend/eval/graders/count_consistency.py
  - backend/eval/graders/loader.py
  - backend/eval/judge_chat_v2.py
  - docs/eval-strategy.md
  - backend/eval/datasets/extended-multi-turn-40.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/eval/migrations/v1_to_v2_schema.py
  - backend/eval/graders/__init__.py
  - backend/eval/migrations/__init__.py
tests:
  - backend/tests/test_judge_chat_v2.py
  - backend/tests/test_grader_ordinal_resolution.py
  - backend/tests/test_runner_aggregate_v2.py
  - backend/tests/test_grader_chunk_recall_grouped.py
  - backend/tests/test_v1_to_v2_migration.py
  - backend/tests/test_grader_count_consistency.py
  - backend/tests/test_runner_plugin_discovery.py
  - backend/tests/test_grader_contradict.py
-->

---
### Requirement: chat-rag v1 → v2 migration script SHALL preserve every item without losing data

A one-shot migration script at `backend/eval/migrations/v1_to_v2_schema.py` SHALL convert every item in the v1 `extended-multi-turn-40.json` to v2 schema with deterministic, lossless field mapping:

- `expected_answer_keywords` → DROPPED (no auto-conversion to `expected_answer_summary`; the latter is set to the literal string `"PENDING AUDIT"` so the grader treats this item as unverified)
- `expected_episode_uuids` (single-tier) → moved to `expected_episode_uuids_must` (conservative: every prior expectation becomes a hard requirement)
- `ground_truth_chunk_ids` (single-tier) → moved to `ground_truth_chunk_ids_must`
- `expected_tool_calls_required` / `expected_tool_calls_acceptable` → carried over unchanged
- `audit_status` → set to `"pending"` for every item EXCEPT the 7 试水 audited items (b22 / b27 / b29 / b11 / b15 / b14 / mt01), which SHALL be manually overwritten with the v2 entries from `docs/case-studies/chat-rag-dataset-audit-2026-05-25.md`

The script SHALL fail loudly (non-zero exit) if any item lacks fields required for migration; it SHALL NOT silently drop fields. The script SHALL write the result to a new file `backend/eval/datasets/extended-multi-turn-40.v2.json` first; the runner integration test SHALL pass against this file before the original is overwritten.

#### Scenario: migration converts every item without data loss

- **GIVEN** the v1 dataset with 40 items
- **WHEN** `python backend/eval/migrations/v1_to_v2_schema.py --input extended-multi-turn-40.json --output extended-multi-turn-40.v2.json` is executed
- **THEN** the output file SHALL contain exactly 40 items
- **AND** every item's `id` SHALL be present in the output
- **AND** no item SHALL be dropped or merged

#### Scenario: 7 audited items carry human-verified status after migration

- **GIVEN** the v2 dataset post-migration plus manual audit overlay
- **WHEN** the 7 audited item ids (b22, b27, b29, b11, b15, b14, mt01) are inspected
- **THEN** each SHALL carry `audit_status: "human-verified-2026-05-25"` or `"human-verified-2026-05-26"`
- **AND** each SHALL carry a populated `expected_answer_summary` (not `"PENDING AUDIT"`)
- **AND** the remaining 33 items SHALL carry `audit_status: "pending"`

#### Scenario: migration script refuses on missing required field

- **GIVEN** a v1 item lacking the `question` field
- **WHEN** the migration script runs
- **THEN** the script SHALL exit with non-zero status
- **AND** the error message SHALL name the offending item id and the missing field
- **AND** the output file SHALL NOT be created


<!-- @trace
source: eval-judge-incorporate-tool-grounding
updated: 2026-05-26
code:
  - backend/eval/prompts/chat_judge_v2.md
  - backend/eval/migrations/audit_overlay_2026_05_26.py
  - backend/eval/runner_v2_aggregate.py
  - backend/scripts/run_chat_agent_eval_v2.py
  - backend/eval/graders/answer_contradict_check.py
  - backend/eval/graders/ordinal_resolution.py
  - backend/eval/graders/chunk_recall_grouped.py
  - backend/eval/graders/count_consistency.py
  - backend/eval/graders/loader.py
  - backend/eval/judge_chat_v2.py
  - docs/eval-strategy.md
  - backend/eval/datasets/extended-multi-turn-40.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/eval/migrations/v1_to_v2_schema.py
  - backend/eval/graders/__init__.py
  - backend/eval/migrations/__init__.py
tests:
  - backend/tests/test_judge_chat_v2.py
  - backend/tests/test_grader_ordinal_resolution.py
  - backend/tests/test_runner_aggregate_v2.py
  - backend/tests/test_grader_chunk_recall_grouped.py
  - backend/tests/test_v1_to_v2_migration.py
  - backend/tests/test_grader_count_consistency.py
  - backend/tests/test_runner_plugin_discovery.py
  - backend/tests/test_grader_contradict.py
-->

---
### Requirement: expected_answer_keywords field SHALL be rejected on v2 items

After this change, the chat-rag dataset validator SHALL reject any item carrying the legacy `expected_answer_keywords` field. The migration script removes it; the v2 schema SHALL NOT permit reintroduction. The replacement is `expected_answer_summary` (natural language, LLM-judge grader) plus optional `expected_answer_aliases` for ASR / synonym handling.

#### Scenario: v2 item with legacy keywords field fails validation

- **GIVEN** a v2 dataset item carrying both `expected_answer_summary` and `expected_answer_keywords`
- **WHEN** the JSON Schema validator runs
- **THEN** validation SHALL fail
- **AND** the error SHALL identify `expected_answer_keywords` as a forbidden field for `schema_version: "2.0"`

<!-- @trace
source: eval-judge-incorporate-tool-grounding
updated: 2026-05-26
code:
  - backend/eval/prompts/chat_judge_v2.md
  - backend/eval/migrations/audit_overlay_2026_05_26.py
  - backend/eval/runner_v2_aggregate.py
  - backend/scripts/run_chat_agent_eval_v2.py
  - backend/eval/graders/answer_contradict_check.py
  - backend/eval/graders/ordinal_resolution.py
  - backend/eval/graders/chunk_recall_grouped.py
  - backend/eval/graders/count_consistency.py
  - backend/eval/graders/loader.py
  - backend/eval/judge_chat_v2.py
  - docs/eval-strategy.md
  - backend/eval/datasets/extended-multi-turn-40.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/eval/migrations/v1_to_v2_schema.py
  - backend/eval/graders/__init__.py
  - backend/eval/migrations/__init__.py
tests:
  - backend/tests/test_judge_chat_v2.py
  - backend/tests/test_grader_ordinal_resolution.py
  - backend/tests/test_runner_aggregate_v2.py
  - backend/tests/test_grader_chunk_recall_grouped.py
  - backend/tests/test_v1_to_v2_migration.py
  - backend/tests/test_grader_count_consistency.py
  - backend/tests/test_runner_plugin_discovery.py
  - backend/tests/test_grader_contradict.py
-->