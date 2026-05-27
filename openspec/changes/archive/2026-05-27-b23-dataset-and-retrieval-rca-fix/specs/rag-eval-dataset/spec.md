## ADDED Requirements

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
