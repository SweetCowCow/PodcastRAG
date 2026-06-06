## ADDED Requirements

### Requirement: Conditional HyDE activation is gated by a default-off flag

The system SHALL expose a boolean setting `hyde_conditional_activation` defaulting to `False`. Two-stage conditional retrieval SHALL run only when `enable_hyde_retrieval` is `True` AND `hyde_conditional_activation` is `True`. All other flag combinations SHALL be bit-equivalent to the pre-change behavior: when `enable_hyde_retrieval` is `False` no HyDE code path is entered; when `enable_hyde_retrieval` is `True` and `hyde_conditional_activation` is `False` HyDE is generated unconditionally exactly as in the `hyde-retrieval-landing` implementation.

#### Scenario: Both flags off or master off preserves baseline

- **WHEN** `enable_hyde_retrieval` is `False` (regardless of `hyde_conditional_activation`)
- **THEN** no HyDE code path is entered and the semantic vector fed to `retrieve_hybrid` is the embedding of the original (or rewritten) question

#### Scenario: Conditional off preserves unconditional HyDE

- **WHEN** `enable_hyde_retrieval` is `True` and `hyde_conditional_activation` is `False`
- **THEN** HyDE is generated unconditionally and its document embedding substitutes the chunk-recall semantic vector, identical to the landing behavior

### Requirement: Two-stage retrieval activates HyDE only on detected lexical mismatch

When both flags are on, the system SHALL first run a base chunk retrieval using the original-question embedding, then measure the lexical overlap ratio between the tokenized question and the text of the top-N base hits. The system SHALL generate HyDE and run a second retrieval (substituting the HyDE document embedding for the chunk-recall semantic vector) ONLY when the measured overlap ratio is strictly below `hyde_mismatch_overlap_threshold`. When the overlap ratio is at or above the threshold, the system SHALL return the base retrieval result and SHALL NOT make any HyDE-generation LLM call, embedding call, or second retrieval.

#### Scenario: High overlap skips HyDE

- **WHEN** both flags are on and the question-to-top-N overlap ratio is at or above `hyde_mismatch_overlap_threshold`
- **THEN** the base retrieval result is returned
- **AND** no HyDE-generation LLM call, embedding call, or second retrieval is made

#### Scenario: Low overlap triggers HyDE second stage

- **WHEN** both flags are on and the question-to-top-N overlap ratio is strictly below `hyde_mismatch_overlap_threshold`
- **THEN** HyDE is generated, its embedding substitutes the chunk-recall semantic vector, and a second retrieval is run whose result is returned
- **AND** the lexical (BM25) question and `route_episodes` embedding remain the original (or rewritten) question / base embedding

##### Example: overlap computation

- **GIVEN** question tokens {中老年, 開工, 年輕, 差異} and top-N hit text containing none of those tokens
- **WHEN** the overlap ratio is computed
- **THEN** the ratio is at or near 0.0 and (assuming threshold 0.3) the HyDE second stage is triggered

### Requirement: Conditional activation fails open to the base retrieval result

The system SHALL treat any failure in overlap computation or HyDE generation/embedding during two-stage retrieval as a fail-open condition: the base retrieval result is returned, a warning is logged, and the request completes without raising. A failure in the conditional path SHALL NOT produce a 5xx response.

#### Scenario: HyDE generation failure in two-stage falls back

- **WHEN** both flags are on, lexical mismatch is detected, and the HyDE-generation call raises
- **THEN** the base retrieval result is returned and the request completes successfully without a 5xx error

### Requirement: Conditional activation exposes mismatch observability fields

The system SHALL record, on the HyDE result object, whether two-stage conditional mode ran, the measured overlap ratio, and whether HyDE was triggered by detected mismatch. The prefilter-rank diagnostic endpoint SHALL surface these fields.

#### Scenario: Diagnostic surfaces overlap and trigger state

- **WHEN** a query runs through two-stage conditional retrieval
- **THEN** the result records the measured overlap ratio and whether HyDE was triggered by mismatch
- **AND** the prefilter-rank diagnostic response includes those fields
