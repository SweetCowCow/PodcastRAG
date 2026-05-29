## ADDED Requirements

### Requirement: Judge pipeline SHALL integrate four DeepEval built-in metrics for chat eval

The chat eval judge layer SHALL invoke four DeepEval metric classes (`AnswerRelevancyMetric`, `ContextualPrecisionMetric`, `FaithfulnessMetric`, `AnswerSimilarityMetric`) for every item, producing a numeric score in `[0, 1]` per metric per item. The DeepEval LLM client SHALL be configured to use the existing `OPENAI_API_KEY` environment variable (the AI Hub key) so no additional secret management is required.

#### Scenario: DeepEval metrics run during chat eval

- **WHEN** the runner processes any dataset item with a non-null `expected_answer_summary` and a non-empty retrieved chunk set
- **THEN** the item's `indicators` object SHALL contain `answer_relevancy`, `contextual_precision`, `faithfulness_deepeval`, and `answer_similarity` entries
- **AND** each entry SHALL include a numeric `score`, a boolean `passed`, and a `details` object with the DeepEval rubric reason

#### Scenario: DeepEval LLM call failure is non-fatal

- **WHEN** the DeepEval client returns an error during metric computation for an item
- **THEN** that indicator's entry for that item SHALL be `{score: null, passed: false, details: {error: <reason>}}`
- **AND** the runner SHALL continue processing remaining items

### Requirement: Judge SHALL provide a custom `context_entity_recall` grader via DeepEval GEval

The judge pipeline SHALL include a `context_entity_recall` grader implemented as a DeepEval `GEval` custom rubric. The rubric SHALL ask the judge LLM to identify entities (people, episode titles, song / album / book titles, organisations) present in the ground-truth answer summary AND check whether the retrieved chunks collectively contain those entities. The score SHALL be `entities_found / entities_total` rounded to 2 decimals.

#### Scenario: entity recall reflects entity coverage in retrieved chunks

- **WHEN** the ground-truth answer summary mentions 3 distinct entities and the retrieved chunks collectively cover 2 of them
- **THEN** `context_entity_recall.score` SHALL be `0.67`
- **AND** `context_entity_recall.details.entities` SHALL list each entity with a `found: bool` flag

### Requirement: Existing self-written graders SHALL preserve byte-equivalent behavior after this change

The existing six self-written graders — `chunk_recall_grouped`, `count_consistency`, `ordinal_resolution`, `answer_contradict_check`, `refusal_appropriateness`, `pronoun_attribution_check` — SHALL continue running with identical behavior to their pre-change implementation. After this change, their output schema, scoring logic, and grader plugin registration SHALL be byte-equivalent to the baseline.

#### Scenario: re-running the previous baseline produces identical self-written grader scores

- **WHEN** the runner is invoked against the same dataset and prod backend commit used for `baseline-post-judge-v2-2026-05-27.json`
- **THEN** the six self-written indicator scores per item SHALL match the baseline file within floating-point tolerance
- **AND** any divergence SHALL be treated as a regression to be investigated, not as a feature change
