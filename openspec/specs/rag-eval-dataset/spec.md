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

LLM-auto-generated items SHALL pass human review before inclusion in a main dataset. Review SHALL be graded: every staged item carries a `pre_review` block with a `review_grade` of `light` or `heavy`, where light items receive a quick per-item human pass and heavy items receive full per-item scrutiny (question, anchor chunk text, rubric assessment, retrieval rank). No item SHALL skip human review regardless of grade. Writing to a main dataset SHALL continue to require the `--target-main`, `--reviewed-by`, and `--reviewed-at` parameters together, and reviewed items SHALL additionally reference the review-log round that approved them.

#### Scenario: Staging is the only unreviewed destination

- **WHEN** the generation script runs without review metadata
- **THEN** output SHALL be written only to the staging file and the main dataset SHALL remain untouched

#### Scenario: Graded review covers every item

- **WHEN** a staged batch contains both light and heavy graded items
- **THEN** the review workflow SHALL present every item to the human reviewer, with heavy items rendered with full anchor context

#### Scenario: Approved item carries review provenance

- **WHEN** an approved item is written to the main dataset
- **THEN** it SHALL carry reviewer id, review timestamp, and the review round it was approved in


<!-- @trace
source: eval-loop-automation
updated: 2026-07-03
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/_review_log.jsonl
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/gcp_batch_transcribe/episodes.jsonl
  - skills-lock.json
  - backend/eval/scripts/promote_reviewed.py
  - backend/eval/scripts/show_profile.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/eval/datasets/profiles/this-not-that-cool.json
  - backend/eval/scripts/review_log.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/eval/datasets/yi-jia-yi.json
  - backend/eval/datasets/profiles/yi-jia-yi.json
  - backend/eval/scripts/__init__.py
  - docs/roadmap.md
  - backend/eval/datasets/_pending_review.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
tests:
  - backend/tests/test_show_profile.py
  - backend/tests/test_review_log_promote.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_build_golden_set_v2.py
-->

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

---
### Requirement: Chunk-level GT audit SHALL verify pronoun reference matches the question's subject

When a dataset auditor selects `ground_truth_chunk_ids_must` or `ground_truth_chunk_ids_either` entries for a chat-rag v2 item, the auditor SHALL verify that the chunk's narrative refers to the same subjects that the item's question asks about. Specifically, when the question is about two or more named people (e.g., "迪拉 跟 Leo 王 怎麼從不認識變成合作夥伴"), the auditor SHALL inspect each candidate chunk's pronouns and noun phrases and confirm that those refer to the question's subjects rather than to a different relationship that merely involves one of the subjects as a bystander.

When the chunk's narrative is about a different relationship (e.g., a chunk where person A introduces person B to person C — the question asks about A↔B but the chunk is about B↔C), the auditor SHALL NOT place that chunk in `ground_truth_chunk_ids_must`. Such chunks MAY be recorded in `ground_truth_chunk_ids_acceptable` as bystander context with an audit note explaining why it is not a must.

Each dataset item with non-empty chunk-level ground truth SHALL record an `audit_notes` field summarising the pronoun-reference verification result for at least one of its GT chunks.

#### Scenario: Two-subject question rejects a chunk where one subject is bystander

- **GIVEN** an item with `question = "迪拉跟 Leo 王怎麼從不認識變成合作夥伴？"`
- **AND** a candidate chunk whose text reads "我（小老虎）的緣分也是我第一次來到台北，迪拉給我安排演出在 Revolver，那次 Leo 王來當暖場嘉賓"
- **WHEN** the auditor performs pronoun-reference verification
- **THEN** the auditor SHALL determine that the chunk's "我" refers to 小老虎, not to 迪拉 nor to Leo 王
- **AND** SHALL determine that the chunk's narrative is about 小老虎↔Leo 王 (with 迪拉 as bystander/intermediary)
- **AND** SHALL NOT place this chunk in `ground_truth_chunk_ids_must`
- **AND** MAY place this chunk in `ground_truth_chunk_ids_acceptable` with an audit note such as "迪拉 only acted as venue arranger; chunk is about 小老虎-Leo 王 relationship"

#### Scenario: Audit note records pronoun-reference verification result

- **GIVEN** an item being audited has at least one chunk in `ground_truth_chunk_ids_must`
- **WHEN** the auditor finalises the GT selection
- **THEN** the item SHALL include an `audit_notes` string field
- **AND** the `audit_notes` SHALL contain at least one sentence describing which subjects each must-chunk refers to (e.g., "EP107 @1766.87: 迪拉 自述 在 Live house 看 表演 被 Leo 王 主動 自我介紹; 主體 = 迪拉↔Leo 王 ✓")


<!-- @trace
source: b23-dataset-and-retrieval-rca-fix
updated: 2026-05-27
code:
  - docs/roadmap.md
  - src/releaseLog.jsx
-->

---
### Requirement: Distributed evidence questions SHALL use the `either` tier rather than empty must

When a dataset item's answer comes from a pattern observable across multiple distinct chunks rather than from a single chunk (e.g., "除了來賓以外，哪些人經常參與節目" — answer is a pattern across many episodes mentioning the recurring participant names), the auditor SHALL NOT leave `ground_truth_chunk_ids_must` empty by default. Instead the auditor SHALL build a `ground_truth_chunk_ids_either` structure where each evidence chunk (for each expected entity in the answer) is grouped such that hitting any one chunk for a given expected entity counts as evidence for that entity.

When the item's expected answer enumerates N distinct entities (e.g., three recurring participants), the auditor SHALL collect at least one transcript or description chunk per entity for the `either` tier, and the audit note SHALL explain the per-entity grouping logic.

When no transcript or description evidence exists for any expected entity, the auditor MAY leave the GT empty, but the audit note SHALL explicitly state "no chunk-level evidence available; this item is graded by LLM judge only" so future readers do not mistake an audit gap for a deliberate empty-GT design.

#### Scenario: Three-entity recurring-participants question uses three-group either

- **GIVEN** an item with `question = "除了來賓以外，哪些人經常參與節目？"`
- **AND** expected answer enumerates three recurring participants: 杜宗祐, 方品融, 阿名
- **WHEN** the auditor searches transcripts and descriptions
- **AND** finds at least one chunk mentioning each of the three names (in any episode)
- **THEN** the auditor SHALL populate `ground_truth_chunk_ids_either` with all chunks containing those names
- **AND** the `audit_notes` SHALL describe the per-entity grouping logic (e.g., "杜宗祐 has 5 transcript chunks across EP119/EP52/...; 方品融 has 2 chunks in EP94; 阿名 has 1 transcript + 3 description chunks")

#### Scenario: Empty GT requires explicit audit note when no evidence exists

- **GIVEN** an item whose answer cannot be grounded in any transcript or description chunk
- **WHEN** the auditor finalises the GT selection
- **THEN** `ground_truth_chunk_ids_must` MAY be empty
- **AND** `ground_truth_chunk_ids_either` MAY be empty
- **AND** the `audit_notes` field SHALL contain the literal phrase "no chunk-level evidence available"

<!-- @trace
source: b23-dataset-and-retrieval-rca-fix
updated: 2026-05-27
code:
  - docs/roadmap.md
  - src/releaseLog.jsx
-->

---
### Requirement: A `_calibration_8` dataset SHALL exist for prompt fingerprint diff use

The repository SHALL ship a small calibration golden set at `backend/eval/datasets/_calibration_8.json` containing 8 items selected from `extended-multi-turn-40.json` to cover representative `design_type` values: `show_overview`, `guest_find`, `topic_find`, `date_find`, `deep_dive` (with EP-ref), `cross_episode`, `multi_turn`, and `negative`. The file SHALL be a strict subset of the parent dataset (same item shape, no edits) and SHALL be regenerable via a documented selection rule.

#### Scenario: calibration set covers design type spectrum

- **WHEN** an operator opens `_calibration_8.json`
- **THEN** the file SHALL contain exactly 8 items
- **AND** each `design_type` value among the eight items SHALL appear at most twice (allowing one design_type to repeat if multi_turn is treated as its own type)
- **AND** each item SHALL be a verbatim copy of the corresponding item in `extended-multi-turn-40.json`


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Calibration set SHALL be documented as the prompt fingerprint diff input

The dataset README (or accompanying inventory doc) SHALL document the calibration set's purpose: prompt change PRs run `prompt_fingerprint_diff.py` against this set to detect retrieval-side fingerprint drift before merging. The documentation SHALL state that the full 34-item golden set is NOT the input (too expensive per PR) and SHALL warn against using `_calibration_8` for any other measurement purpose.

#### Scenario: dataset README mentions calibration set purpose

- **WHEN** an operator opens `backend/eval/datasets/README.md`
- **THEN** the file SHALL include a section describing `_calibration_8.json` and its prompt fingerprint diff use case
- **AND** the section SHALL state the 8-item-not-34-item rationale (per-PR cost)

<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->