## MODIFIED Requirements

### Requirement: Tool registry exposes eleven callables backed by real services

The backend SHALL register exactly fourteen callables in `chat_agent.tools.TOOLS`. This count comprises the original eleven from `agentic-framework-bakeoff`'s 9-tool spec (with tool 7 split into `search_within_episode` / `search_across_episodes` / `search_in_episodes` and tool 9 split into `pin_episode` / `unpin_episode`), plus `list_episodes` and `find_episodes_by_date` (added by prior changes without spec sync — recorded here for spec ↔ code alignment), plus `search_with_topic_prefilter` added by change `retrieval-cross-episode-episode-prefilter`. Each callable SHALL declare a Pydantic `BaseModel` as its input schema. The OpenAI tool function schema SHALL be derived from that Pydantic model automatically (no hand-written JSON Schema). All previously stubbed tools from the bake-off SHALL be wired to production services:

- `get_episode_summary` SHALL read from the episode summary store via `summary_pipeline`.
- `get_episode_segments` SHALL read from `topic_segmentation`.
- `search_within_episode` and `search_in_episodes` SHALL call `rag.retrieve_hybrid` with `episode_id_filter` set.
- `search_across_episodes` SHALL call `rag.retrieve_hybrid` without an episode filter. Its tool description SHALL note that it is the fallback path; for questions spanning a known topic / theme across episodes, the LLM SHOULD prefer `search_with_topic_prefilter` to avoid topic-related-but-wrong-episode chunks dominating the merged pool.
- `search_with_topic_prefilter` SHALL internally call `episode_finders.find_episodes_by_topic(show_id, [topic])` to obtain a candidate episode set, then call `rag.retrieve_hybrid` with `episode_id_filter` set to the candidate set. When the candidate set is empty, the tool SHALL fall back to `rag.retrieve_hybrid` without an episode filter (matching `search_across_episodes` behavior) so the caller still receives some chunks rather than an empty result.
- `find_episode_by_ref` SHALL call `episode_finders.find_by_ref`.
- `find_episodes_by_guest` / `find_episodes_by_topic` / `find_episodes_by_date` / `list_episodes` SHALL call the corresponding `episode_finders` functions.
- `get_show_overview` SHALL read from the show table.
- `pin_episode` and `unpin_episode` SHALL write to `ChatSessionState.focused_episode_id`.

#### Scenario: Input schema validation failure returns error JSON to LLM

- **GIVEN** the LLM emits a tool call with an argument that fails the Pydantic `BaseModel` validation (e.g., `episode_id="not-a-uuid"`)
- **WHEN** `_dispatch_tool` validates the arguments
- **THEN** the tool function body SHALL NOT be executed
- **AND** the tool-result message SHALL contain `{"error": "ValidationError: ..."}` with the validation detail
- **AND** the agent SHALL continue the loop so the LLM can apologise to the user

#### Scenario: Enumeration tool writes back to L1 state

- **GIVEN** the LLM calls `find_episodes_by_topic(topic="歌單")` and the function returns episode UUIDs
- **WHEN** the tool dispatcher records the result
- **THEN** the dispatcher SHALL also update the current `ChatSessionState.last_enumeration_episodes` with the returned episode UUIDs (most recent up to 20, FIFO truncated)
- **AND** the dispatcher SHALL update `ChatSessionState.last_enumeration_at` to the current timestamp
- **AND** the state SHALL be persisted to Redis with TTL refreshed

## ADDED Requirements

### Requirement: search_with_topic_prefilter SHALL pre-scope retrieval to topic-matching episodes

The `search_with_topic_prefilter(topic: str, query: str, k: int = 5)` tool SHALL execute the following two-step retrieval:

1. Call `episode_finders.find_episodes_by_topic(show_id, [topic])` to obtain a candidate episode list `candidates`.
2. If `len(candidates) > 0`, call `rag.retrieve_hybrid(query, episode_id_filter=[ep.episode_id for ep in candidates], k=k)`.
3. If `len(candidates) == 0`, fall back to `rag.retrieve_hybrid(query, k=k)` without filter so the caller still receives chunks (degraded gracefully, equivalent to `search_across_episodes`).

The tool result envelope SHALL include:

- `chunks`: same shape as other search tools (list of dicts via `_chunk_to_dict`)
- `prefilter_episode_count`: integer, the size of `candidates` returned by the topic finder
- `fallback_to_full_pool`: boolean, `true` when step 3 (empty-candidate fallback) was taken, `false` when step 2 ran

#### Scenario: Topic match returns candidates, retrieval is scoped to them

- **GIVEN** the show contains episodes EP143, EP107, EP66 whose `find_episodes_by_topic(topic="家常味")` returns `[EP143, EP107]`
- **AND** the LLM calls `search_with_topic_prefilter(topic="家常味", query="馬世芳怎麼定義家常味", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL pass `episode_id_filter=[EP143_uuid, EP107_uuid]`
- **AND** the returned envelope's `prefilter_episode_count` SHALL equal `2`
- **AND** the envelope's `fallback_to_full_pool` SHALL be `false`
- **AND** no returned chunk SHALL have an `episode_id` outside `{EP143_uuid, EP107_uuid}`

#### Scenario: No topic match falls back to full-show retrieval without filter

- **GIVEN** `find_episodes_by_topic(topic="lorem-ipsum-no-match")` returns an empty list
- **AND** the LLM calls `search_with_topic_prefilter(topic="lorem-ipsum-no-match", query="any question", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL be invoked WITHOUT an `episode_id_filter` (full show pool)
- **AND** the returned envelope's `prefilter_episode_count` SHALL equal `0`
- **AND** the envelope's `fallback_to_full_pool` SHALL be `true`
- **AND** `chunks` MAY contain up to `k` results spanning any episode

#### Scenario: Envelope fields are always populated

- **GIVEN** any successful invocation of `search_with_topic_prefilter`
- **WHEN** the tool dispatcher records the result
- **THEN** the envelope SHALL contain the keys `chunks`, `prefilter_episode_count`, and `fallback_to_full_pool` regardless of whether the prefilter path or fallback path executed
- **AND** the chunk dict shape SHALL be identical to that returned by `search_across_episodes` and `search_in_episodes` (so downstream `_collect_agentic_citations` does not need branching)

#### Scenario: Tool description guides LLM away from search_across_episodes for topical questions

- **GIVEN** the OpenAI tool schema generated from `SearchWithTopicPrefilterInput`
- **WHEN** the schema is rendered to the LLM
- **THEN** the description string SHALL explicitly recommend this tool over `search_across_episodes` for questions that name a topic / theme spanning multiple episodes
- **AND** the `search_across_episodes` tool description SHALL be updated to call itself the "fallback" path and refer the LLM to `search_with_topic_prefilter` for topical cross-episode queries
