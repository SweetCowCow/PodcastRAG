## ADDED Requirements

### Requirement: find_episode_by_ref SHALL auto-pin resolved episode to session focused state

When the agent invokes `find_episode_by_ref(ref=...)` and the underlying `episode_finders.find_by_ref` call returns a non-None `EpisodeRef`, the tool dispatcher SHALL write the resolved `episode_id` into `ChatSessionState.focused_episode_id` AND SHALL set `ChatSessionState.focused_episode_at` to the current UTC timestamp, BEFORE returning the tool result to the LLM. The tool result envelope returned to the LLM SHALL include an `auto_pinned: true` field so the LLM can observe that the episode is now in session focus. When the resolver returns None (no episode matched), session state SHALL NOT be modified and the envelope SHALL contain `auto_pinned: false`.

#### Scenario: Resolved episode is auto-pinned

- **GIVEN** an empty `ChatSessionState` with `focused_episode_id = None`
- **AND** the agent calls `find_episode_by_ref(ref="EP143")` which resolves to episode `<EP143-uuid>`
- **WHEN** the tool dispatcher records the result
- **THEN** `ChatSessionState.focused_episode_id` SHALL be set to `<EP143-uuid>`
- **AND** `ChatSessionState.focused_episode_at` SHALL be set to the current UTC timestamp
- **AND** the tool result envelope SHALL contain `auto_pinned: true`
- **AND** the state SHALL be persisted to Redis with TTL refreshed

#### Scenario: Failed resolution does not modify session state

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <existing-uuid>`
- **AND** the agent calls `find_episode_by_ref(ref="EP9999")` which returns None
- **WHEN** the tool dispatcher records the result
- **THEN** `ChatSessionState.focused_episode_id` SHALL remain `<existing-uuid>`
- **AND** the tool result envelope SHALL contain `auto_pinned: false`

#### Scenario: Auto-pin overwrites prior focused episode

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP140-uuid>` (set by an earlier turn's auto-pin)
- **AND** the agent in the current turn calls `find_episode_by_ref(ref="EP19")` which resolves to `<EP19-uuid>`
- **WHEN** the tool dispatcher records the result
- **THEN** `ChatSessionState.focused_episode_id` SHALL be overwritten to `<EP19-uuid>`
- **AND** `ChatSessionState.focused_episode_at` SHALL be updated to the current UTC timestamp

---

### Requirement: Episode-scoped tools SHALL fall back to session focused_episode_id when episode_id arg is omitted

The tools `search_within_episode`, `get_episode_segments`, and `get_episode_summary` (which all require an `episode_id` to scope their query) SHALL, in their dispatcher pre-processing step, check whether the LLM provided a non-empty `episode_id` argument:

- If `episode_id` is provided explicitly and non-empty, the dispatcher SHALL use it as-is. The tool result envelope SHALL include `episode_id_source: "explicit"`.
- If `episode_id` is omitted or empty AND `ChatSessionState.focused_episode_id` is non-None, the dispatcher SHALL substitute `ChatSessionState.focused_episode_id` as the effective `episode_id` before invoking the underlying service. The tool result envelope SHALL include `episode_id_source: "session_focused"` AND `effective_episode_id: <uuid>`.
- If both are absent, the dispatcher SHALL return an error envelope with `episode_id_source: "missing"` and a `user_hint` describing that no episode is in focus and the LLM should call `find_episode_by_ref` first.

#### Scenario: Explicit episode_id is preserved

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP143-uuid>`
- **AND** the agent calls `search_within_episode(query="家常味", episode_id="<EP140-uuid>")`
- **WHEN** the tool dispatcher pre-processes the call
- **THEN** the underlying retrieve call SHALL use `<EP140-uuid>` (NOT the session focused id)
- **AND** the tool result envelope SHALL contain `episode_id_source: "explicit"`

#### Scenario: Omitted episode_id falls back to session focused

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP143-uuid>` from a prior auto-pin
- **AND** the agent calls `search_within_episode(query="RAG")` without an `episode_id` argument
- **WHEN** the tool dispatcher pre-processes the call
- **THEN** the underlying retrieve call SHALL use `<EP143-uuid>` (substituted from session)
- **AND** the tool result envelope SHALL contain `episode_id_source: "session_focused"` AND `effective_episode_id: "<EP143-uuid>"`

#### Scenario: Both missing returns guided error envelope

- **GIVEN** a `ChatSessionState` with `focused_episode_id = None`
- **AND** the agent calls `get_episode_segments()` without an `episode_id` argument
- **WHEN** the tool dispatcher pre-processes the call
- **THEN** the underlying service SHALL NOT be invoked
- **AND** the tool result envelope SHALL contain `episode_id_source: "missing"` AND a `user_hint` string instructing the LLM to call `find_episode_by_ref` first

#### Scenario: Fallback applies to get_episode_summary

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP140-uuid>`
- **AND** the agent calls `get_episode_summary()` without an `episode_id` argument in a follow-up turn
- **WHEN** the tool dispatcher pre-processes the call
- **THEN** the underlying summary service SHALL be invoked with `<EP140-uuid>`
- **AND** the tool result envelope SHALL contain `episode_id_source: "session_focused"`

---

### Requirement: pin_episode SHALL be idempotent when target episode is already focused

The `pin_episode(episode_id=X)` tool SHALL succeed without raising an error when `ChatSessionState.focused_episode_id` already equals `X` (e.g., because an earlier `find_episode_by_ref` already auto-pinned X). In this idempotent path the tool result envelope SHALL contain `ok: true` AND `already_pinned: true` so the LLM can distinguish "newly pinned" from "no-op". When `focused_episode_id` is None or differs from X, `pin_episode` SHALL proceed with the standard write (existing behavior) and the envelope SHALL contain `ok: true` AND `already_pinned: false`.

#### Scenario: Pin to currently-focused episode is a no-op

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP143-uuid>` (auto-pinned earlier)
- **AND** the agent calls `pin_episode(episode_id="<EP143-uuid>")`
- **WHEN** the tool dispatcher processes the call
- **THEN** the tool result envelope SHALL contain `ok: true` AND `already_pinned: true`
- **AND** `ChatSessionState.focused_episode_at` MAY be refreshed to the current UTC timestamp (but otherwise no state change)
- **AND** no error or warning SHALL be raised to the LLM

#### Scenario: Pin to different episode performs normal write

- **GIVEN** a `ChatSessionState` with `focused_episode_id = <EP143-uuid>`
- **AND** the agent calls `pin_episode(episode_id="<EP140-uuid>")`
- **WHEN** the tool dispatcher processes the call
- **THEN** `ChatSessionState.focused_episode_id` SHALL be updated to `<EP140-uuid>`
- **AND** the tool result envelope SHALL contain `ok: true` AND `already_pinned: false`

#### Scenario: Pin from empty state performs normal write

- **GIVEN** a `ChatSessionState` with `focused_episode_id = None`
- **AND** the agent calls `pin_episode(episode_id="<EP19-uuid>")`
- **WHEN** the tool dispatcher processes the call
- **THEN** `ChatSessionState.focused_episode_id` SHALL be set to `<EP19-uuid>`
- **AND** the tool result envelope SHALL contain `ok: true` AND `already_pinned: false`
