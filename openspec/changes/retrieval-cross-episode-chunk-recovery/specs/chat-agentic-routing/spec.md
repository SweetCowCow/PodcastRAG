# chat-agentic-routing Delta

## MODIFIED Requirements

### Requirement: search_with_topic_prefilter SHALL pre-scope retrieval to topic-matching episodes

The `search_with_topic_prefilter(topic: str, query: str, k: int = 5)` tool SHALL execute the following retrieval pipeline:

1. Call `episode_finders.find_episodes_by_topic(show_id, [topic])` to obtain a candidate episode list `candidates`.
2. If `len(candidates) > 0`, call `rag.retrieve_hybrid(query, episode_id_filter=[ep.episode_id for ep in candidates], k=50)` to obtain an expanded candidate chunk pool `top_n_chunks`. If `len(candidates) == 0`, fall back to `rag.retrieve_hybrid(query, k=k)` without filter and skip rerank (return directly with `rerank_applied=false`).
3. When the prefilter path executed in step 2, invoke `rag.rerank.llm_rerank(question=query, chunks=top_n_chunks, k=k)` to obtain the final `k` chunks. The rerank stage SHALL use `gemini-2.5-flash-lite` via the existing LLM client. The rerank LLM SHALL receive the question plus each chunk's `chunk_id` and a text excerpt, and SHALL return a JSON `{"ranked_chunk_ids": [...]}` whose order determines the final selection.
4. When the rerank call fails (timeout > 1.5s, non-2xx response, malformed JSON, or output references chunk_ids absent from `top_n_chunks`), the tool SHALL fall back to the original RRF order of `top_n_chunks[:k]` and SHALL set `rerank_applied=false`. Unknown chunk_ids in the LLM output SHALL be discarded; if fewer than `k` valid chunks remain, the gap SHALL be filled from the original RRF order.

The tool result envelope SHALL include:

- `chunks`: same shape as other search tools (list of dicts via `_chunk_to_dict`)
- `prefilter_episode_count`: integer, the size of `candidates` returned by the topic finder
- `fallback_to_full_pool`: boolean, `true` when the empty-candidate fallback path was taken, `false` when the prefilter path ran
- `rerank_applied`: boolean, `true` when LLM rerank successfully returned a usable ranking, `false` otherwise (including the empty-candidate fallback path)
- `rerank_input_count`: integer, the number of chunks sent to the rerank stage (`len(top_n_chunks)`, which is at most 50 and may be smaller when the prefilter pool has fewer than 50 chunks). When the empty-candidate fallback path was taken, this field SHALL be `0`.

#### Scenario: Topic match returns candidates, retrieval is scoped to them

- **GIVEN** the show contains episodes EP143, EP107, EP66 whose `find_episodes_by_topic(topic="家常味")` returns `[EP143, EP107]`
- **AND** the LLM calls `search_with_topic_prefilter(topic="家常味", query="馬世芳怎麼定義家常味", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL pass `episode_id_filter=[EP143_uuid, EP107_uuid]` and `k=50`
- **AND** the returned envelope's `prefilter_episode_count` SHALL equal `2`
- **AND** the envelope's `fallback_to_full_pool` SHALL be `false`
- **AND** no returned chunk SHALL have an `episode_id` outside `{EP143_uuid, EP107_uuid}`

#### Scenario: No topic match falls back to full-show retrieval without filter

- **GIVEN** `find_episodes_by_topic(topic="lorem-ipsum-no-match")` returns an empty list
- **AND** the LLM calls `search_with_topic_prefilter(topic="lorem-ipsum-no-match", query="any question", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL be invoked WITHOUT an `episode_id_filter` (full show pool) and with `k=5` (no top-N expand)
- **AND** the returned envelope's `prefilter_episode_count` SHALL equal `0`
- **AND** the envelope's `fallback_to_full_pool` SHALL be `true`
- **AND** the envelope's `rerank_applied` SHALL be `false`
- **AND** the envelope's `rerank_input_count` SHALL be `0`
- **AND** `chunks` MAY contain up to `k` results spanning any episode

#### Scenario: Envelope fields are always populated

- **GIVEN** any successful invocation of `search_with_topic_prefilter`
- **WHEN** the tool dispatcher records the result
- **THEN** the envelope SHALL contain the keys `chunks`, `prefilter_episode_count`, `fallback_to_full_pool`, `rerank_applied`, and `rerank_input_count` regardless of whether the prefilter path, fallback path, or rerank failure path executed
- **AND** the chunk dict shape SHALL be identical to that returned by `search_across_episodes` and `search_in_episodes` (so downstream `_collect_agentic_citations` does not need branching)

#### Scenario: Tool description guides LLM away from search_across_episodes for topical questions

- **GIVEN** the OpenAI tool schema generated from `SearchWithTopicPrefilterInput`
- **WHEN** the schema is rendered to the LLM
- **THEN** the description string SHALL explicitly recommend this tool over `search_across_episodes` for questions that name a topic / theme spanning multiple episodes
- **AND** the `search_across_episodes` tool description SHALL be updated to call itself the "fallback" path and refer the LLM to `search_with_topic_prefilter` for topical cross-episode queries

#### Scenario: Rerank reorders top-50 candidates and returns top-k

- **GIVEN** prefilter path produced 50 candidate chunks `C1..C50` in RRF order
- **AND** the GT chunk `C13` ranks 13th in the RRF order
- **WHEN** `llm_rerank` returns `{"ranked_chunk_ids": ["C13", "C5", "C1", "C19", "C7", ...]}`
- **THEN** the tool SHALL return `chunks` corresponding to `[C13, C5, C1, C19, C7]`
- **AND** the envelope's `rerank_applied` SHALL be `true`
- **AND** the envelope's `rerank_input_count` SHALL equal `50`

#### Scenario: Rerank failure falls back to original RRF order

- **GIVEN** prefilter path produced 50 candidate chunks
- **WHEN** the LLM rerank call times out (exceeds 3.0s), returns non-2xx, returns malformed JSON, or returns `ranked_chunk_ids` whose entries are all absent from the candidate set
- **THEN** the tool SHALL return the first `k` chunks of the original RRF order
- **AND** the envelope's `rerank_applied` SHALL be `false`
- **AND** the envelope's `rerank_input_count` SHALL still report the actual number of chunks sent to rerank (e.g., `50`)
- **AND** no exception SHALL propagate to the agent loop

#### Scenario: Rerank output partially unknown chunk_ids are filtered and back-filled

- **GIVEN** prefilter path produced 50 candidate chunks `C1..C50`
- **AND** the LLM rerank returns `{"ranked_chunk_ids": ["C13", "UNKNOWN_ID", "C5", "C1", "ANOTHER_UNKNOWN", "C9"]}`
- **WHEN** the tool collects the top `k=5` chunks
- **THEN** unknown chunk_ids (`UNKNOWN_ID`, `ANOTHER_UNKNOWN`) SHALL be discarded
- **AND** the kept order SHALL be `[C13, C5, C1, C9]`
- **AND** the 5th slot SHALL be filled from the next chunk in original RRF order that is not already in the kept list
- **AND** the envelope's `rerank_applied` SHALL be `true`

<!-- @trace
source: retrieval-cross-episode-chunk-recovery
updated: 2026-05-26
code:
  - backend/app/services/chat_agent/tools.py
  - backend/app/services/rag_rerank.py
tests:
  - backend/tests/test_chat_agent_topic_prefilter_rerank.py
-->
