## MODIFIED Requirements

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
