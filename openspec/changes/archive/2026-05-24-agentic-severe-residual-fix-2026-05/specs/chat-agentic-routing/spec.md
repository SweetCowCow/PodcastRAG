## ADDED Requirements

### Requirement: find_episode_by_ref SHALL match episode references on word boundaries

The `find_by_ref` SQL helper (`backend/app/services/episode_finders.py::find_by_ref`) SHALL match episode references on word boundaries, NOT on substring containment. When the user reference normalises to episode number `n` (extracted via the `(?:EP|ep|第)\s*(\d+)\s*(?:集)?` regex), the SQL SHALL match titles where the token `EP{n}` or `第{n}集` appears as a standalone token — meaning the character immediately after `{n}` MUST NOT be another digit. The previous `title ILIKE '%EP{n}%'` substring match SHALL be removed.

#### Scenario: EP1 reference resolves to EP1, not EP10/100/146

- **GIVEN** the database contains episodes titled "EP1｜...", "EP10｜...", "EP100｜...", "EP146｜..." in the same show
- **WHEN** the runner calls `find_by_ref(show_id, ref='EP1')`
- **THEN** the returned episode SHALL be the EP1 episode (or `None` if no EP1 exists in this show)
- **AND** the returned episode SHALL NOT be EP10, EP100, or EP146

##### Example: EP1 vs EP146 prod regression case

- **GIVEN** show "這又沒有很屌" contains EP146 titled "EP146｜你們是不是怕沒話聊？Ft. 9m88" (published 2026-05-20) but no EP1 episode
- **WHEN** the agent calls `find_episode_by_ref(ref='EP1')`
- **THEN** the tool SHALL return `None` (or a `{"ok": false, "kind": "not_found"}` envelope)
- **AND** the tool SHALL NOT return EP146

#### Scenario: EP10 reference still resolves correctly

- **GIVEN** the database contains EP10 and EP100 in the same show
- **WHEN** the runner calls `find_by_ref(show_id, ref='EP10')`
- **THEN** the returned episode SHALL be EP10
- **AND** SHALL NOT be EP100

#### Scenario: Chinese ordinal reference resolves correctly

- **GIVEN** the database contains an episode titled "第3集｜...the show theme..."
- **WHEN** the runner calls `find_by_ref(show_id, ref='第3集')`
- **THEN** the returned episode SHALL be that 第3集 episode

### Requirement: Agent loop SHALL log last_enumeration_episodes state at build_messages time under admin debug_trace

When the admin `?debug_trace=true` gate is active, `_build_system_message` (`backend/app/services/chat_agent/memory.py`) SHALL emit a record into the response trace (under a new field on the existing trace structure) capturing the current `state.last_enumeration_episodes` UUID list and the `state.last_enumeration_at` timestamp at the moment the system message is built for the current turn. The record SHALL include the turn's user question for cross-reference with the dataset. When the gate is NOT active, no logging SHALL occur — the response shape and prompt content SHALL be unchanged for normal users.

This requirement creates observability ONLY; it does NOT modify the writeback, persistence, or instruction logic governing ordinal carry. The downstream fix to ordinal carry will land in a separate change once telemetry pinpoints the failing layer.

#### Scenario: Admin trace exposes state at build time

- **GIVEN** an admin session opens a multi-turn dialog and turn 1's enumeration tool populated `state.last_enumeration_episodes` with three UUIDs
- **WHEN** turn 2 issues `POST /shows/{id}/query?debug_trace=true` with question "第三集是什麼內容?"
- **THEN** the response trace SHALL include a record with the three UUIDs (in turn 1's order) and a non-null timestamp
- **AND** the record SHALL include the literal user question "第三集是什麼內容?"

#### Scenario: Non-admin session sees no state log

- **GIVEN** a non-admin session opens the same multi-turn dialog
- **WHEN** turn 2 issues `POST /shows/{id}/query?debug_trace=true`
- **THEN** the response SHALL NOT contain the state log field
- **AND** the prompt content built by `_build_system_message` SHALL be identical to a request without the query param

### Requirement: System prompt SHALL refuse to fabricate host roster changes

The `SYSTEM_PROMPT` constant in `backend/app/services/chat_agent/prompts.py` SHALL include a rule that forbids the agent from inferring or fabricating host roster changes ("主持人陣容變化 / 嘉賓輪替 / 主持人變動歷史" or English equivalents) from episode listings or show overview. The rule SHALL state that unless a tool result explicitly contains text marking a host change in a specific episode, the agent MUST reply with an honest refusal (e.g., "資料庫無主持人變動紀錄") rather than infer a roster timeline from `list_episodes` or `get_show_overview` output.

#### Scenario: Host change query without host_history tool returns honest refusal

- **GIVEN** the user asks "《這又沒有很屌》從第一集到現在，主持人陣容有什麼變化?"
- **AND** no tool result returned to the agent contains explicit host-change marker text
- **WHEN** the agent composes its answer
- **THEN** the answer SHALL contain an honest refusal phrase indicating no host change record is available
- **AND** the answer SHALL NOT list specific host names with implied roster changes (e.g., "初期是 X、後期是 Y")

##### Example: refusal phrasing

- **GIVEN** the user asks the host-roster-change question above
- **WHEN** the agent answers
- **THEN** the answer SHALL include text equivalent to "目前資料庫沒有節目主持人變動的明確紀錄，無法回答主持陣容變化"

### Requirement: Agent answers SHALL flag unverified EP references and quoted strings

Before the agent loop returns a final chat answer to the API layer, the answer text SHALL be scanned against the concatenation of all `tool_calls[].result_full` strings collected during this turn. The scan SHALL apply two regex passes:

1. Every `EP\d+` token in the answer SHALL appear as a substring in the concatenated reference text.
2. Every quoted string enclosed in CJK quotes (`「...」`) or ASCII double quotes (`"..."`) of at least 4 characters SHALL appear as a substring in the concatenated reference text.

Any unmatched token SHALL be **annotated** in-place by appending the suffix `[未驗證]` immediately after the token, **not stripped**. The response object SHALL expose an `unverified_count` integer field on the `ChatResponse` schema indicating how many tokens were annotated (zero when none).

#### Scenario: Real EP reference is not annotated

- **GIVEN** the agent's tool calls returned a `find_episodes_by_date` result containing `"title": "EP69｜Demo徵集2..."`
- **AND** the agent's final answer contains the substring "EP69"
- **WHEN** the post-generation scan runs
- **THEN** the answer SHALL NOT have `[未驗證]` appended after "EP69"
- **AND** `unverified_count` SHALL be 0 for this token

##### Example: b12 partial-fabrication case after fix

- **GIVEN** the agent calls `find_episodes_by_date(start="2024-11-01", end="2024-11-30")` and the tool returns one episode EP69
- **AND** the agent's answer contains "EP69｜Demo徵集2..." and also fabricates "EP70｜...", "EP71｜..."
- **WHEN** the post-generation scan runs
- **THEN** "EP69" SHALL NOT be annotated
- **AND** "EP70" SHALL be followed by "[未驗證]"
- **AND** "EP71" SHALL be followed by "[未驗證]"
- **AND** `unverified_count` SHALL be 2

#### Scenario: Fabricated quote is annotated

- **GIVEN** the agent's tool calls returned chunks NOT containing the string "我覺得這就是安身之處"
- **AND** the agent's final answer contains `「我覺得這就是安身之處」`
- **WHEN** the post-generation scan runs
- **THEN** the answer SHALL have `[未驗證]` appended after the closing quote
- **AND** `unverified_count` SHALL be at least 1

#### Scenario: Short quoted strings are not scanned

- **GIVEN** the agent's answer contains `「好」` (3 characters or fewer)
- **WHEN** the post-generation scan runs
- **THEN** the short quote SHALL NOT be checked or annotated
