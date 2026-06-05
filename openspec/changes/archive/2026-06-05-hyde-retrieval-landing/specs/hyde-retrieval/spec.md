## ADDED Requirements

### Requirement: HyDE retrieval is gated by a default-off flag

The system SHALL expose a boolean setting `enable_hyde_retrieval` defaulting to `False`. When the flag is `False`, the three semantic retrieve entry points (`public_search_show`, `query_show` search mode, `query_show` chat rule-based path) SHALL behave identically to the pre-change implementation: a single embedding of the original (or history-rewritten) question, no additional LLM call, no HyDE code path entered.

#### Scenario: Flag off preserves baseline behavior

- **WHEN** `enable_hyde_retrieval` is `False` and a caller queries any of the three entry points
- **THEN** the semantic vector fed to `retrieve_hybrid` is the embedding of the original (or rewritten) question
- **AND** no HyDE-generation LLM call is made

#### Scenario: Flag on substitutes the HyDE document embedding

- **WHEN** `enable_hyde_retrieval` is `True` and HyDE generation succeeds
- **THEN** the semantic vector fed to `retrieve_hybrid` is the embedding of the generated hypothetical-answer text
- **AND** the lexical (BM25) question passed to `retrieve_hybrid` remains the original (or rewritten) question

### Requirement: Episode routing always uses the original question embedding

The system SHALL pass the original (or history-rewritten) question's embedding to `route_episodes` regardless of the `enable_hyde_retrieval` flag. The HyDE document embedding SHALL only influence the chunk-level `retrieve_hybrid` call, never the episode-selection routing.

#### Scenario: Routing unaffected by HyDE

- **WHEN** `enable_hyde_retrieval` is `True`
- **THEN** `route_episodes` receives the embedding of the original (or rewritten) question, not the HyDE document embedding

### Requirement: HyDE generation fails open to the original embedding

The system SHALL treat any HyDE-generation failure (step not configured, client construction error, LLM error, empty response) as a fail-open condition: the semantic vector falls back to the original question embedding, a warning is logged, and the retrieve path proceeds without raising. A HyDE failure SHALL NOT produce a 5xx response.

#### Scenario: LLM error falls back without 5xx

- **WHEN** `enable_hyde_retrieval` is `True` and the HyDE-generation LLM call raises
- **THEN** the semantic vector falls back to the original question embedding
- **AND** the request completes successfully without a 5xx error

### Requirement: Landing keeps the default flag value off pending A/B evidence

The system SHALL ship this change with `enable_hyde_retrieval` defaulting to `False`. Flipping the default to `True` is a separate decision gated on an expanded-sample flag on/off A/B measurement and human approval; this change SHALL NOT flip the default.

#### Scenario: Default remains off after landing

- **WHEN** this change is merged and deployed without an explicit override
- **THEN** `enable_hyde_retrieval` evaluates to `False`
