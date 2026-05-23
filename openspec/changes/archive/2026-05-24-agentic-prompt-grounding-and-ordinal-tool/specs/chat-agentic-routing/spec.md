## MODIFIED Requirements

### Requirement: Tool registry exposes twelve callables backed by real services

The backend SHALL register exactly twelve callables in `chat_agent.tools.TOOLS`. Eleven callables correspond to nine numbered tools from `agentic-framework-bakeoff`'s 9-tool spec (with tool 7 split into `search_within_episode` / `search_across_episodes` / `search_in_episodes` and tool 9 split into `pin_episode` / `unpin_episode`). The twelfth callable is `list_episodes`, added to cover recency-driven query intent (newest / oldest N, optionally filtered by topic and / or calendar-year range). Each callable SHALL declare a Pydantic `BaseModel` as its input schema. The OpenAI tool function schema SHALL be derived from that Pydantic model automatically (no hand-written JSON Schema). All previously stubbed tools from the bake-off SHALL be wired to production services:

- `get_episode_summary` SHALL read from the episode summary store via `summary_pipeline`.
- `get_episode_segments` SHALL read from `topic_segmentation`.
- `search_within_episode` and `search_in_episodes` SHALL call `rag.retrieve_hybrid` with `episode_id_filter` set.
- `search_across_episodes` SHALL call `rag.retrieve_hybrid` without an episode filter.
- `find_episode_by_ref` SHALL call `episode_finders.find_by_ref`.
- `find_episodes_by_guest` / `find_episodes_by_topic` / `find_episodes_by_date` SHALL call the corresponding `episode_finders` functions.
- `get_show_overview` SHALL read from the show table.
- `pin_episode` and `unpin_episode` SHALL write to `ChatSessionState.focused_episode_id`.
- `list_episodes` SHALL call a new `episode_finders.find_episodes_by_recency` helper.

The `list_episodes` tool input schema SHALL accept these keyword arguments: `show_id: UUID` (required), `n: int = 5` (max 20, raise validation error otherwise), `order: Literal['newest', 'oldest'] = 'newest'`, `topic: str | None = None`, `year_start: int | None = None`, `year_end: int | None = None`. Year filter SHALL apply `EXTRACT(YEAR FROM published_at AT TIME ZONE 'Asia/Taipei')`. Topic filter SHALL reuse the same `episode_description_chunks` tsquery logic that `find_episodes_by_topic` already uses (CJK simple_cjk analyzer). The tool output SHALL be a dict `{"episodes": list[EpisodeRef], "n_returned": int, "n_total_matched": int}` where `n_total_matched` reports the total rows matching filters before LIMIT is applied (gives the agent visibility when more results exist than requested).

Additionally, `find_episodes_by_date_range` SHALL accept two new optional keyword arguments: `order: Literal['newest', 'oldest'] = 'newest'` (defaulting to `'newest'` preserves the existing `ORDER BY published_at DESC` behavior) and `limit: int | None = None` (defaulting to `None` preserves the existing unbounded behavior; any positive integer caps the result set). Existing callers (rule-based path in `/query` endpoint) SHALL continue to work unchanged.

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

#### Scenario: list_episodes returns newest episodes by default

- **GIVEN** a show with 8 transcribed episodes whose `published_at` ranges from 2024-01-01 to 2025-05-01
- **WHEN** the LLM calls `list_episodes(show_id=<id>, n=3)` (default `order='newest'`)
- **THEN** the dispatcher SHALL return a dict with `episodes` containing the 3 most recent episodes ordered DESC by `published_at`
- **AND** `n_returned` SHALL equal 3
- **AND** `n_total_matched` SHALL equal 8

#### Scenario: list_episodes order='oldest' reverses ordering

- **GIVEN** the same 8-episode show
- **WHEN** the LLM calls `list_episodes(show_id=<id>, n=5, order='oldest')`
- **THEN** the result `episodes` SHALL contain the 5 oldest episodes ordered ASC by `published_at`
- **AND** `n_returned` SHALL equal 5
- **AND** `n_total_matched` SHALL equal 8

#### Scenario: list_episodes combines topic and year_range filters

- **GIVEN** a show with episodes spanning 2023-2025, of which 4 episodes mention "歌單" in their description and 2 of those 4 were published in 2024
- **WHEN** the LLM calls `list_episodes(show_id=<id>, n=1, topic='歌單', year_start=2024, year_end=2024, order='oldest')`
- **THEN** the result `episodes` SHALL contain exactly 1 episode (the oldest 2024 episode mentioning 歌單)
- **AND** `n_total_matched` SHALL equal 2

#### Scenario: list_episodes rejects n > 20

- **WHEN** the LLM calls `list_episodes(show_id=<id>, n=25)`
- **THEN** Pydantic validation SHALL fail with a `n` field error
- **AND** the tool result envelope SHALL be `{"ok": false, "kind": "validation", ...}` with a user-friendly hint mentioning the 20-episode cap

#### Scenario: list_episodes returns empty when no episodes match filters

- **GIVEN** a show with no 2024 episodes
- **WHEN** the LLM calls `list_episodes(show_id=<id>, n=5, year_start=2024, year_end=2024)`
- **THEN** the result SHALL be `{"episodes": [], "n_returned": 0, "n_total_matched": 0}`
- **AND** the tool SHALL NOT raise an exception

#### Scenario: find_episodes_by_date_range with limit caps result count

- **GIVEN** a date range matching 10 episodes
- **WHEN** `find_episodes_by_date_range(db, show_id, start, end, limit=3)` is called
- **THEN** the result SHALL contain exactly 3 EpisodeRef rows ordered DESC by `published_at`

#### Scenario: find_episodes_by_date_range with order='oldest' reverses sort

- **GIVEN** a date range matching 5 episodes
- **WHEN** `find_episodes_by_date_range(db, show_id, start, end, order='oldest', limit=2)` is called
- **THEN** the result SHALL contain the 2 oldest episodes within the range ordered ASC by `published_at`

#### Scenario: find_episodes_by_date_range backwards-compat (no new kwargs)

- **GIVEN** an existing caller invokes `find_episodes_by_date_range(db, show_id, start, end)` with no new keyword arguments
- **THEN** the result ordering SHALL be DESC by `published_at` (newest first) and SHALL contain all matching episodes (no limit applied)

---

### Requirement: System prompt instructs tool-eager grounded behaviour and forbids fabrication of six fact categories

The agent's system prompt (`chat_agent.prompts.SYSTEM_PROMPT`) SHALL contain four sections, in this order:

1. A role description identifying the agent as PodcastRAG's chat agent.
2. A tool-eager instruction stating that the agent MUST call at least one tool before refusing or answering whenever the user asks about specific information (episode numbers, hosts, guests, content).
3. A grounded-refusal instruction stating that when all relevant tools return empty, the agent MUST explicitly say it cannot find X rather than fabricate, and when input schema is invalid, the agent MUST ask the user to clarify rather than guess.
4. A fact-grounding instruction explicitly listing **six categories of content that the agent MUST NOT fabricate**; these categories can only be quoted directly from a tool result or from the user's input. The six categories SHALL be:
   1. Show title (節目名稱)
   2. Host / guest name (來賓 / 嘉賓姓名)
   3. EP number (EP 編號)
   4. Episode title (集數標題)
   5. Verbatim quote attributed to a host or guest (引號內的話)
   6. Statistical numbers (e.g., "X 集", "N 次提到", "總共 M 分鐘")

When the tool results do not provide enough information for the agent to answer accurately about any of the six fabrication-forbidden categories, the agent MUST explicitly say "資料不足，無法確認" (or English equivalent) rather than guess. Content NOT in the six categories (overall show tendency, topic commentary, cross-episode synthesis) MAY be inferred from tool results, but the answer SHALL include a closing disclaimer (e.g., "以上分析基於 tool 取得的內容，請以節目實際內容為準") signalling the inference nature.

The fact-grounding section SHALL also include a tool routing hint: "需要 sort 或限定數量 → list_episodes 或 find_episodes_by_date_range 帶 limit；需要列出全部符合條件的集數 → 用既有 find_episodes_by_* 系列無 limit。"

#### Scenario: Specific-information query triggers tool call

- **GIVEN** the user asks "馬世芳上過哪一集？" (a specific information query about a guest)
- **WHEN** the agent processes the request
- **THEN** the agent SHALL call at least one tool (e.g., `find_episodes_by_guest`) before producing the final answer
- **AND** the answer SHALL NOT be a flat refusal without any tool invocation

#### Scenario: Recency query routes to list_episodes

- **GIVEN** the user asks "最新一集的來賓是誰？" (a recency-intent question)
- **WHEN** the agent processes the request
- **THEN** the agent SHALL call `list_episodes(show_id=<current_show>, n=1)` (or `n` between 1 and 5) as one of its first tool calls
- **AND** the agent SHALL NOT respond with a flat refusal nor with an empty `tool_calls` list
- **AND** the final answer SHALL reference the actual episode title or EP number returned by `list_episodes`

#### Scenario: Answer SHALL NOT fabricate show title

- **GIVEN** the user asks "馬世芳上過這個節目嗎？" while focused on show "這又沒有很屌"
- **AND** the relevant tools return episode results referencing "這又沒有很屌" but no other show
- **WHEN** the agent generates the final answer
- **THEN** the answer SHALL only mention the show title "這又沒有很屌" (or rephrase it as "本節目" / "this show")
- **AND** the answer SHALL NOT mention any other show title not appearing in the tool results (e.g., the answer SHALL NOT say "節目《也好吃》" if "也好吃" was never in tool results or user input)

#### Scenario: Answer SHALL NOT fabricate verbatim quotes

- **GIVEN** the user asks "馬世芳怎麼評論 AI 泡沫？"
- **AND** the tools return episode descriptions and summary chunks but no exact quote text
- **WHEN** the agent generates the final answer
- **THEN** the answer SHALL NOT include text wrapped in 「」 or "" attributed to 馬世芳 unless that exact text appears verbatim in a tool result

#### Scenario: Insufficient tool result triggers explicit insufficiency disclaimer

- **GIVEN** the user asks "最新一集講了什麼？" and `list_episodes(n=1)` returns the episode metadata but `get_episode_summary` returns empty
- **WHEN** the agent generates the final answer
- **THEN** the answer SHALL include text like "資料不足，無法確認" or "目前我沒有取得這集的詳細內容" rather than fabricate a content summary

#### Scenario: Inference content SHALL include disclaimer

- **GIVEN** the user asks "這個節目的整體風格偏向？"
- **AND** the tools return episode descriptions and topic chunks
- **WHEN** the agent generates the final answer using these as inference inputs
- **THEN** the answer SHALL include a closing disclaimer (e.g., "以上分析基於 tool 取得的內容，請以節目實際內容為準") signalling the inference nature
