## ADDED Requirements

### Requirement: Chat agent SHALL dispatch explicit episode references to `find_episode_by_ref` first

When the user question contains an explicit episode reference — defined as one of (a) `EP\d+` pattern (e.g. `EP134`, `EP19`), (b) `第\s*\d+\s*集` pattern (e.g. `第 134 集`, `第140集`), or (c) a quoted episode title (e.g. `《動漫歌單》`) — the chat agent SHALL choose `find_episode_by_ref` as its first tool call, and SHALL follow up with `search_within_episode` (or `get_episode_summary` if the question is summary-shaped) within the same turn. The agent SHALL NOT fall back to `search_with_topic_prefilter` or global `retrieve_hybrid` for these queries as a first action.

#### Scenario: EP-number reference triggers episode-scoped dispatch

- **WHEN** the user asks "迪拉胖在 EP134 為什麼不挑一首振奮的開工歌？"
- **THEN** the agent's first tool call SHALL be `find_episode_by_ref` with the episode reference token
- **AND** the second tool call SHALL be `search_within_episode` (or `get_episode_summary` for summary-shaped queries)

#### Scenario: 第N集 reference triggers episode-scoped dispatch

- **WHEN** the user asks "第 140 集第二彈是哪兩位來賓？"
- **THEN** the agent's first tool call SHALL be `find_episode_by_ref`
- **AND** the agent SHALL NOT call `retrieve_hybrid` or `search_with_topic_prefilter` as the first action

#### Scenario: no episode reference falls back to global retrieval

- **WHEN** the user asks "節目裡有講過咖啡的集數有哪些？" (no EP-ref)
- **THEN** the agent SHALL use its existing dispatch logic (e.g. `search_with_topic_prefilter` or `retrieve_hybrid`)
- **AND** the EP-ref rule SHALL NOT influence the dispatch

### Requirement: `search_within_episode` tool description SHALL declare priority for episode-referenced queries

The tool schema description for `search_within_episode` SHALL include language declaring that it is the first-choice tool whenever the user names a specific episode by number, `EP\d+` reference, or quoted title, and SHALL explicitly state that the agent should NOT fall back to global search for these queries.

#### Scenario: tool description carries priority hint

- **WHEN** the agent reads the available tools schema
- **THEN** the `search_within_episode` description SHALL contain text equivalent to "whenever the user names a specific episode by number, EP-ref, or title, this is the first choice — do NOT fall back to global search for these queries"
