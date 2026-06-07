## ADDED Requirements

### Requirement: Cross-episode topical questions are deterministically routed to topic-prefilter search

The system SHALL apply a deterministic first-turn routing nudge so that cross-episode topical / narrative questions use `search_with_topic_prefilter` (candidate-scoping + voyage rerank) instead of relying on the LLM's free `tool_choice`, which empirically selects the un-scoped `search_across_episodes`. When the current user turn is detected as a cross-episode topical question, the system SHALL force the first agentic LLM call's `tool_choice` to `search_with_topic_prefilter`; once that tool returns, subsequent rounds SHALL revert to `tool_choice="auto"`. The nudge SHALL be controlled by a default-on boolean setting `enable_topic_routing_nudge`; when the setting is `False`, tool selection SHALL be bit-equivalent to the prior `tool_choice="auto"` behavior on every round.

The detector SHALL favor precision over recall: it SHALL classify a turn as cross-episode topical only when the question is NOT scoped to a specific episode reference (no `EPnnn` / `第n集` / 「這集」/「上一集」 style reference) AND the question yields at least two discriminating topic tokens (using the existing jieba topic-term extraction with stop-word and show-name removal). Turns that do not meet both conditions SHALL NOT be force-routed and SHALL keep `tool_choice="auto"`.

#### Scenario: Cross-episode topical question forces topic-prefilter on the first call

- **WHEN** a user asks a cross-episode topical question with ≥2 discriminating topic tokens and no specific episode reference
- **AND** `enable_topic_routing_nudge` is `True`
- **THEN** the first agentic LLM call SHALL be issued with `tool_choice` forcing `search_with_topic_prefilter`
- **AND** rounds after that tool returns SHALL use `tool_choice="auto"`

#### Scenario: Episode-scoped question is not force-routed

- **WHEN** a user question references a specific episode (e.g. contains `EP107` or 「這集」)
- **THEN** the routing nudge SHALL NOT fire
- **AND** the first agentic LLM call SHALL use `tool_choice="auto"`

#### Scenario: Question with fewer than two discriminating tokens is not force-routed

- **WHEN** a user question reduces to fewer than two discriminating topic tokens after filtering
- **THEN** the routing nudge SHALL NOT fire
- **AND** tool selection SHALL match the prior `tool_choice="auto"` behavior

#### Scenario: Flag off preserves prior behavior

- **WHEN** `enable_topic_routing_nudge` is `False`
- **THEN** every agentic LLM call SHALL use `tool_choice="auto"` regardless of the detector outcome
