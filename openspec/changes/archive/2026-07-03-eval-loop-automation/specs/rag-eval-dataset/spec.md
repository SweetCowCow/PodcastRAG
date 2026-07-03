## MODIFIED Requirements

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
