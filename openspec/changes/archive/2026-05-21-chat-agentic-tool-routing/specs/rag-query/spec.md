## ADDED Requirements

### Requirement: Chat-mode dispatches to agent loop when feature flag is enabled

When `settings.enable_agentic_chat` is `true` AND the request `payload.mode` is not `"search"`, the `query_show` endpoint SHALL dispatch the request to `chat_agent.agent.run_agent` instead of executing the rule-based pipeline (rewrite → entity extraction → metadata filter → `retrieve_hybrid` → enumeration → answer). When `settings.enable_agentic_chat` is `false`, the rule-based pipeline SHALL continue to execute unchanged. The search-mode branch (`payload.mode == "search"`) SHALL NOT be affected by the flag in either state.

#### Scenario: Flag enabled, chat-mode request → agent loop

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and a request with `payload.mode != "search"`
- **WHEN** `query_show` handles the request
- **THEN** `chat_agent.agent.run_agent` SHALL be called
- **AND** the rule-based pipeline branch (rewrite + entity extraction + `_compute_enumeration_episodes`) SHALL NOT execute

#### Scenario: Flag disabled, chat-mode request → rule-based pipeline

- **GIVEN** `ENABLE_AGENTIC_CHAT=false` and a request with `payload.mode != "search"`
- **WHEN** `query_show` handles the request
- **THEN** the rule-based pipeline SHALL execute as before
- **AND** `chat_agent.agent.run_agent` SHALL NOT be called

#### Scenario: Search-mode unaffected by flag

- **GIVEN** any value of `ENABLE_AGENTIC_CHAT` and a request with `payload.mode == "search"`
- **WHEN** `query_show` handles the request
- **THEN** the search-mode branch SHALL execute the existing pipeline (embed → optional routing → `retrieve_hybrid` → enrich)
- **AND** `chat_agent.agent.run_agent` SHALL NOT be called

### Requirement: Quota accounting applies uniformly across both pipelines

The per-user query quota check and atomic decrement SHALL be performed before pipeline dispatch and SHALL behave identically regardless of whether the request is routed to the agent loop or the rule-based pipeline. Once dispatched, an agent-loop failure (e.g., iteration cap exhausted, all tools failing) SHALL NOT trigger an automatic quota refund unless the rule-based pipeline would have refunded under equivalent conditions.

#### Scenario: Quota decremented before dispatch

- **GIVEN** an authenticated chat-mode request
- **WHEN** `query_show` enters the chat branch
- **THEN** the user's quota SHALL be decremented before either `run_agent` or the rule-based pipeline is invoked
- **AND** the decrement SHALL behave identically across both pipelines
