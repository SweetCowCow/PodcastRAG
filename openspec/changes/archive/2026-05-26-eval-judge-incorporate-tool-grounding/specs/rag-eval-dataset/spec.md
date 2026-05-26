## ADDED Requirements

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

---

### Requirement: expected_answer_keywords field SHALL be rejected on v2 items

After this change, the chat-rag dataset validator SHALL reject any item carrying the legacy `expected_answer_keywords` field. The migration script removes it; the v2 schema SHALL NOT permit reintroduction. The replacement is `expected_answer_summary` (natural language, LLM-judge grader) plus optional `expected_answer_aliases` for ASR / synonym handling.

#### Scenario: v2 item with legacy keywords field fails validation

- **GIVEN** a v2 dataset item carrying both `expected_answer_summary` and `expected_answer_keywords`
- **WHEN** the JSON Schema validator runs
- **THEN** validation SHALL fail
- **AND** the error SHALL identify `expected_answer_keywords` as a forbidden field for `schema_version: "2.0"`

## REMOVED Requirements

### Requirement: extended-multi-turn-40 dataset SHALL carry ground_truth_chunk_ids on scored turns

**Reason**: superseded by the v2 schema's three-tier `ground_truth_chunk_ids_must / _either / _acceptable` field. The single-tier `ground_truth_chunk_ids` field is migrated to `_must` by the v1 → v2 migration script and SHALL NOT remain as a top-level grader contract after migration.

**Migration**: run `backend/eval/migrations/v1_to_v2_schema.py`. The script automatically moves any non-null `ground_truth_chunk_ids` into `ground_truth_chunk_ids_must`. Audited items (試水 7 題) get their `_either` / `_acceptable` tiers added manually from the case-study overlay.

#### Scenario: legacy single-tier ground_truth_chunk_ids is migrated to _must

- **GIVEN** a v1 item carrying `ground_truth_chunk_ids: ["ep:abc@1.00"]`
- **WHEN** the migration script runs
- **THEN** the v2 output item SHALL contain `ground_truth_chunk_ids_must: ["ep:abc@1.00"]`
- **AND** the top-level `ground_truth_chunk_ids` field SHALL be absent from the v2 item
