## ADDED Requirements

### Requirement: ChatSessionState models per-session conversational anchors

The backend SHALL define `backend/app/services/chat_agent/state.py::ChatSessionState` as a Pydantic `BaseModel` containing exactly these fields:

- `session_id: UUID` — supplied by the frontend (UUID v4); the backend SHALL NOT auto-generate one.
- `focused_episode_id: UUID | None`
- `focused_episode_at: datetime | None` — UTC, set whenever `focused_episode_id` is written.
- `last_enumeration_episodes: list[UUID]` — most-recent enumeration result, capped at 20 entries with FIFO truncation.
- `last_enumeration_at: datetime | None` — UTC, set whenever `last_enumeration_episodes` is written.
- `history_summary: str` — running summary, capped at ≤ 300 characters.
- `created_at: datetime` — UTC, set on first persistence.
- `updated_at: datetime` — UTC, updated on every persistence.

Field validation SHALL be performed by Pydantic. The `last_enumeration_episodes` list SHALL be truncated FIFO when its length would exceed 20.

#### Scenario: Enumeration list truncated to 20

- **GIVEN** `state.last_enumeration_episodes` already contains 18 entries
- **WHEN** a tool writes back 5 new episode UUIDs in one call
- **THEN** the resulting list SHALL contain exactly 20 entries
- **AND** the 3 oldest entries SHALL have been dropped (FIFO)

### Requirement: Redis persistence with 2h TTL and refresh-on-write

The state store SHALL persist `ChatSessionState` to Redis under key `chat:session:{session_id}` using JSON serialisation. Every write SHALL set the key's TTL to `settings.agentic_chat_l1_ttl_seconds` (default 7200 seconds = 2 hours). Reads SHALL return `None` for missing keys and the store SHALL NOT auto-create rows; first write happens lazily when the agent first mutates state.

#### Scenario: TTL refreshed on every write

- **GIVEN** a state row already exists in Redis with TTL `T1`
- **WHEN** the agent writes a new value via the state store
- **THEN** the key TTL SHALL be reset to `settings.agentic_chat_l1_ttl_seconds`

#### Scenario: Missing session returns None, no auto-create

- **GIVEN** Redis has no key `chat:session:{session_id}`
- **WHEN** the state store reads the session
- **THEN** the read SHALL return `None`
- **AND** no key SHALL be written to Redis

### Requirement: Lazy expiry of focused episode and enumeration anchors

When `ChatSessionState` is loaded from Redis, the loader SHALL apply lazy expiry rules before returning the model:

- If `focused_episode_at` is not null AND `now - focused_episode_at > settings.agentic_chat_focused_idle_seconds` (default 600s = 10 min), the loader SHALL set both `focused_episode_id` and `focused_episode_at` to `None` in the returned model.
- If `last_enumeration_at` is not null AND `now - last_enumeration_at > settings.agentic_chat_enumeration_ttl_seconds` (default 600s = 10 min), the loader SHALL set both `last_enumeration_episodes = []` and `last_enumeration_at = None` in the returned model.

Lazy expiry SHALL NOT write back to Redis on read; writes happen only when the agent mutates state.

#### Scenario: Focused episode expired after 11 minutes idle

- **GIVEN** `focused_episode_at` was set 11 minutes ago
- **WHEN** the state store loads the session
- **THEN** the returned `focused_episode_id` SHALL be `None`
- **AND** the returned `focused_episode_at` SHALL be `None`

#### Scenario: Enumeration list expired after 11 minutes

- **GIVEN** `last_enumeration_at` was set 11 minutes ago
- **WHEN** the state store loads the session
- **THEN** `last_enumeration_episodes` SHALL be `[]`
- **AND** `last_enumeration_at` SHALL be `None`

### Requirement: System prompt injects active anchors with ordinal instruction

When the agent builds messages for the next LLM call, it SHALL inject the non-expired anchors into the system message:

- If `focused_episode_id` is not `None`, the system message SHALL include the line `Focused episode: <episode_id>`.
- If `last_enumeration_episodes` is non-empty, the system message SHALL include the list as `Last enumeration: [<ep_id_0>, <ep_id_1>, ...]` AND the line `若使用者說「第 N 集」，請對應 last_enumeration[N-1] 的 ep_id；若 N 超出範圍或語意不明，請使用者澄清而非自行翻譯為 EP<N>`.

#### Scenario: Ordinal reference resolves through L1 anchor

- **GIVEN** `last_enumeration_episodes = [ep_A, ep_B, ep_C, ep_D, ep_E]` and the user says "第三集是什麼內容？"
- **WHEN** the agent processes the turn
- **THEN** the next tool call SHALL be `get_episode_summary(episode_id=ep_C)` (the third entry)
- **AND** the agent SHALL NOT call `find_episode_by_ref(ref="EP3")` (the bake-off failure mode)

### Requirement: history_summary updated incrementally with fail-open semantics

After each completed agent turn, the system SHALL invoke `update_history_summary(state, last_turn)` to refresh `state.history_summary` using `gemini-2.5-flash-lite` (or equivalent low-cost model configured under the `summary` AI step). Summarisation SHALL be capped to ≤ 300 characters. If summarisation raises any exception, the failure SHALL be logged but SHALL NOT abort the main response; the previous `history_summary` SHALL be retained as-is.

#### Scenario: Summary failure does not block main response

- **GIVEN** the summary LLM is unreachable (network error)
- **WHEN** `update_history_summary` is invoked after a turn
- **THEN** the exception SHALL be logged
- **AND** `state.history_summary` SHALL retain its previous value
- **AND** the agent's main response SHALL still be returned to the user
