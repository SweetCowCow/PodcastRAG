## ADDED Requirements

### Requirement: Agentic path populates chunk-level citations from search-tool results

When `ENABLE_AGENTIC_CHAT=true` serves a chat-mode query, the `_agent_result_to_response` mapper in `backend/app/api/query.py` SHALL populate `ChatResponse.citations` by aggregating chunks from the `result_full["chunks"]` payload of every `ToolCallTrace` whose `name` is one of `search_within_episode`, `search_across_episodes`, or `search_in_episodes` and whose `raised` is null. The aggregation SHALL deduplicate by `chunk_id`, sort by `rrf_score` descending, and emit the top 5 entries as `ChunkHit` instances. When the agent invoked no successful search tool, `citations` SHALL be an empty list, matching the pre-flip behavior.

When a tool's `result_full` does not match the expected `{"chunks": [...]}` shape (missing key, wrong type, malformed entries), the mapper SHALL skip that tool call, log a warning, and continue processing remaining tool calls. The mapper SHALL NOT raise an exception that would surface as an HTTP 5xx to the caller.

#### Scenario: Agent invokes search_within_episode and citations are populated

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls `search_within_episode` once, returning 8 chunks
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.citations` SHALL contain 5 `ChunkHit` entries
- **AND** the entries SHALL be sorted by `rrf_score` descending
- **AND** each entry's `chunk_id` SHALL be unique

#### Scenario: Agent invokes multiple search tools and citations are deduplicated

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls both `search_across_episodes` and `search_within_episode`, with two overlapping `chunk_id` values
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.citations` SHALL NOT contain duplicate `chunk_id` values
- **AND** the entry list length SHALL be at most 5

#### Scenario: Agent invokes only listing tools and citations stay empty

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent only calls `find_episodes_by_guest`
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.citations` SHALL be `[]`

#### Scenario: Malformed tool result is skipped without 5xx

- **GIVEN** a `search_within_episode` tool call whose `result_full` is missing the `chunks` key
- **WHEN** `_agent_result_to_response` processes the result
- **THEN** that tool call SHALL be skipped
- **AND** the mapper SHALL log a warning
- **AND** the function SHALL return a valid `ChatResponse` (not raise an exception)

### Requirement: Agentic path populates enumeration_episodes from listing-tool results

When `ENABLE_AGENTIC_CHAT=true` serves a chat-mode query, the `_agent_result_to_response` mapper SHALL populate `ChatResponse.enumeration_episodes` by aggregating episode entries from the `result_full` payload of every `ToolCallTrace` whose `name` is one of `find_episodes_by_guest`, `find_episodes_by_topic`, or `find_episodes_by_date` and whose `raised` is null. The aggregation SHALL deduplicate by `episode_id`, preserve the order in which the agent observed them, and emit each entry as an `EpisodeRef` instance.

When the agent invoked no successful listing tool, `enumeration_episodes` SHALL remain `None` (the schema default), so that the frontend `EnumerationSection` collapses, matching the rule-based pipeline's behavior on non-enumeration queries.

#### Scenario: Agent invokes find_episodes_by_guest and enumeration is populated

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls `find_episodes_by_guest(name="楊大正")`, returning 2 episodes
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.enumeration_episodes` SHALL contain 2 `EpisodeRef` entries
- **AND** the entries SHALL preserve agent-observed order

#### Scenario: Agent invokes multiple listing tools and entries are deduplicated

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent calls both `find_episodes_by_topic` and `find_episodes_by_date`, with one overlapping `episode_id`
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.enumeration_episodes` SHALL NOT contain duplicate `episode_id` values

#### Scenario: Agent invokes only search tools and enumeration stays null

- **GIVEN** `ENABLE_AGENTIC_CHAT=true` and the agent only calls `search_within_episode`
- **WHEN** `query_show` returns the chat response
- **THEN** `ChatResponse.enumeration_episodes` SHALL be `null`

### Requirement: ENABLE_AGENTIC_CHAT Python default SHALL be true

The `enable_agentic_chat` field on `Settings` in `backend/app/core/config.py` SHALL default to `True`. The `if settings.enable_agentic_chat` branch in `query_show` and the rule-based pipeline below it SHALL remain in place for at least 30 days after the default flip, serving as a `ENABLE_AGENTIC_CHAT=false` kill-switch. A subsequent cleanup change SHALL be responsible for removing the flag, the branch, and the rule-based pipeline code once the observation window completes.

#### Scenario: Local backend without env override runs agentic loop

- **GIVEN** a developer runs the backend locally with no `ENABLE_AGENTIC_CHAT` env variable set
- **WHEN** a chat-mode query is dispatched
- **THEN** `query_show` SHALL invoke `run_agent` (not the rule-based pipeline)

#### Scenario: Explicit env false still bypasses agent

- **GIVEN** `ENABLE_AGENTIC_CHAT=false` is set in env
- **WHEN** a chat-mode query is dispatched
- **THEN** `query_show` SHALL invoke the rule-based pipeline (not `run_agent`)

## MODIFIED Requirements

### Requirement: Eval gate blocks rollout of agentic chat default

Before flipping the `enable_agentic_chat` Python default from `False` to `True`, an evaluation run against `backend/eval/datasets/extended-multi-turn-40.json` SHALL be performed against the Arm D (agentic) pipeline using the LLM-as-judge (`backend/scripts/run_llm_judge_multi_turn.py`) calibrated by `_judge_minisset.json`. The agentic pipeline SHALL meet all of the following gates:

- `answer_match_mean` (keyword baseline) MUST NOT drop by more than 5 percentage points vs the stored baseline `backend/eval/results/chat_eval_agentic_2026-05-22.json`.
- LLM judge `answer_quality_mean` MUST be ≥ 0.55 (absolute threshold; no same-dataset baseline available).
- The ratio of turns labelled `hallucination_severity == "severe"` MUST be ≤ 20% of total turns scored.
- Of the four multi-turn dialogs containing ordinal-reference follow-ups, at least 1 SHALL produce an answer that maps to the corresponding `episode_id` from the prior enumeration.

Evaluation results SHALL be persisted under `backend/eval/results/` with a date-stamped filename, and the gate decision SHALL be recorded in the change's design.md before merging the default flip. Stricter thresholds (severe count == 0, ordinal hits ≥ 3/4) were considered and explicitly waived in design.md "2026-05-22 校準紀錄" because the blocking failure modes (LLM grounding weakness, prompt-instruction non-compliance) are not introduced by this change and require an independent follow-up `agentic-prompt-grounding-and-ordinal-tool`.

#### Scenario: answer_match regression blocks default flip

- **GIVEN** the eval run shows agentic `answer_match_mean` more than 5pp below the stored baseline
- **WHEN** anyone proposes flipping the `enable_agentic_chat` Python default
- **THEN** the change SHALL be blocked until the regression is addressed or the gate is explicitly waived with sign-off recorded in design.md

#### Scenario: answer_quality below absolute threshold blocks default flip

- **GIVEN** the eval run shows agentic `answer_quality_mean` below 0.55
- **WHEN** anyone proposes flipping the `enable_agentic_chat` Python default
- **THEN** the change SHALL be blocked until the regression is addressed

#### Scenario: Severe hallucination rate above 20% blocks default flip

- **GIVEN** the eval run shows more than 20% of scored turns with `hallucination_severity == "severe"`
- **WHEN** anyone proposes flipping the `enable_agentic_chat` Python default
- **THEN** the change SHALL be blocked until the offending turns' root cause is addressed

#### Scenario: Zero ordinal-reference hits blocks default flip

- **GIVEN** the eval run shows zero of the four ordinal-reference follow-ups produce the correct prior-enumeration `episode_id`
- **WHEN** anyone proposes flipping the `enable_agentic_chat` Python default
- **THEN** the change SHALL be blocked until at least one ordinal carry path works
