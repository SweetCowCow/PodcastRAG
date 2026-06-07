## ADDED Requirements

### Requirement: Answer-step model must honor forced tool_choice with the full tool spec

The model configured for the `answer` AI step (`ai_steps.answer.model`) SHALL honor OpenAI forced `tool_choice` (a specific `{"type":"function","function":{"name":...}}` selection) when called with the full chat-agent tool spec (`OPENAI_TOOLS_SPEC`, currently 14 tools). This is a precondition for the deterministic first-turn routing nudge (b22 `search_with_topic_prefilter` force) to take effect. Any change to `ai_steps.answer.model` SHALL be validated against this requirement before it is relied upon for routing, because some models (verified: gpt-4o, gpt-4.1-mini via AI Hub) silently ignore forced `tool_choice` under the full spec and fall back to free tool selection, while others (verified: gpt-4.1, gpt-5.1, gemini-2.5-flash, gemini-2.5-pro) honor it.

#### Scenario: Configured answer model honors forced tool_choice

- **GIVEN** `ai_steps.answer.model` is set to the selected model
- **AND** a cross-episode topical question (b23) that the routing detector flags for force
- **WHEN** the chat agent's first LLM call passes `tool_choice` forcing `search_with_topic_prefilter` with the full tool spec
- **THEN** the trace's first tool call SHALL be `search_with_topic_prefilter`

> Note: whether the answer ultimately cites EP107 is NOT part of this requirement.
> The 2026-06-07 bake-off proved EP107 surfacing is bounded by the lexical
> topic-prefilter mechanism (entity-token flooding pushes EP107 out of the
> `ts_rank` cap), independent of the answer model — verified gpt-5.1 0/4 and
> gemini-2.5-pro 1/4 even with correct routing. EP107 reliability is owned by the
> `topic-prefilter-transcript-aware` capability and its follow-up (semantic
> episode selection / entity-token stripping), not by the answer-step model.

#### Scenario: Answer model that ignores forced tool_choice is rejected for routing

- **GIVEN** a candidate model is evaluated for the `answer` step
- **WHEN** it is called with the full tool spec and a forced `tool_choice` for a specific function
- **AND** it returns a different (freely chosen) tool instead of the forced one
- **THEN** that model SHALL NOT be selected as the `answer` step model while b22 deterministic routing is relied upon
