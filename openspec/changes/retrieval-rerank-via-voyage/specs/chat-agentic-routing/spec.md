# chat-agentic-routing Delta

## MODIFIED Requirements

### Requirement: search_with_topic_prefilter SHALL pre-scope retrieval to topic-matching episodes

The `search_with_topic_prefilter(topic: str, query: str, k: int = 5)` tool SHALL execute the following retrieval pipeline:

1. Call `episode_finders.find_episodes_by_topic(show_id, [topic])` to obtain a candidate episode list `candidates`.
2. If `len(candidates) > 0`, call `rag.retrieve_hybrid(query, episode_id_filter=[ep.episode_id for ep in candidates], k=30)` to obtain a candidate chunk pool, then invoke `rag_rerank.voyage_rerank(question=query, chunks=pool, k=k)` to reorder by relevance and return the top `k`. The rerank stage SHALL use the Voyage `rerank-2.5` model via the `voyageai` Python SDK with credentials read from the `VOYAGE_API_KEY` environment variable.
3. If `len(candidates) == 0`, fall back to `rag.retrieve_hybrid(query, k=k)` without filter and skip rerank (return directly with `rerank_applied=false / rerank_input_count=0`).
4. When the rerank call fails (timeout exceeding 3.0s, non-2xx response, malformed response, or output references indices absent from the candidate pool), the tool SHALL fall back to the original RRF order of the top `k` chunks from the candidate pool and SHALL set `rerank_applied=false`. Unknown indices in the Voyage output SHALL be discarded; if fewer than `k` valid chunks remain, the gap SHALL be filled from the original RRF order.

The tool result envelope SHALL include:

- `chunks`: same shape as other search tools (list of dicts via `_chunk_to_dict`)
- `prefilter_episode_count`: integer, the size of `candidates` returned by the topic finder
- `fallback_to_full_pool`: boolean, `true` when the empty-candidate fallback path was taken, `false` when the prefilter path ran
- `rerank_applied`: boolean, `true` when Voyage rerank successfully returned a usable ranking, `false` otherwise (including the empty-candidate fallback path)
- `rerank_input_count`: integer, the number of chunks sent to the rerank stage (`len(pool)`, which is at most 30 and may be smaller when the prefilter pool has fewer than 30 chunks). When the empty-candidate fallback path was taken, this field SHALL be `0`.

#### Scenario: Topic match returns candidates, retrieval is scoped to them

- **GIVEN** the show contains episodes EP143, EP107, EP66 whose `find_episodes_by_topic(topic="家常味")` returns `[EP143, EP107]`
- **AND** the LLM calls `search_with_topic_prefilter(topic="家常味", query="馬世芳怎麼定義家常味", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL pass `episode_id_filter=[EP143_uuid, EP107_uuid]` and `k=30`
- **AND** Voyage rerank SHALL be invoked with the 30-chunk pool
- **AND** the returned envelope's `prefilter_episode_count` SHALL equal `2`
- **AND** the envelope's `fallback_to_full_pool` SHALL be `false`
- **AND** the envelope's `rerank_applied` SHALL be `true` on rerank success
- **AND** the envelope's `rerank_input_count` SHALL equal `30`
- **AND** no returned chunk SHALL have an `episode_id` outside `{EP143_uuid, EP107_uuid}`

#### Scenario: No topic match falls back to full-show retrieval without filter

- **GIVEN** `find_episodes_by_topic(topic="lorem-ipsum-no-match")` returns an empty list
- **AND** the LLM calls `search_with_topic_prefilter(topic="lorem-ipsum-no-match", query="any question", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL be invoked WITHOUT an `episode_id_filter` (full show pool) and with `k=5` (no top-N expand)
- **AND** Voyage rerank SHALL NOT be invoked
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

#### Scenario: Voyage rerank reorders the candidate pool

- **GIVEN** prefilter path produced a 30-chunk candidate pool from `retrieve_hybrid`
- **AND** Voyage `rerank-2.5` returns relevance scores ordering chunk 13 first, chunk 5 second, chunk 1 third
- **WHEN** the tool collects the top `k=5` chunks
- **THEN** the returned `chunks` SHALL be ordered according to Voyage's ranking (chunks 13, 5, 1 in positions 1-3, then 4th and 5th positions from Voyage's ranking)
- **AND** the envelope's `rerank_applied` SHALL be `true`
- **AND** the envelope's `rerank_input_count` SHALL equal `30`

#### Scenario: Voyage rerank failure falls back to original RRF order

- **GIVEN** prefilter path produced a 30-chunk candidate pool
- **WHEN** the Voyage rerank call times out (exceeds 3.0s), returns non-2xx, returns malformed response, or the `VOYAGE_API_KEY` environment variable is unset
- **THEN** the tool SHALL return the first `k` chunks of the original RRF order
- **AND** the envelope's `rerank_applied` SHALL be `false`
- **AND** the envelope's `rerank_input_count` SHALL still report the actual number of chunks sent to (or that would have been sent to) rerank (e.g., `30`)
- **AND** no exception SHALL propagate to the agent loop

#### Scenario: Voyage rerank output partially unknown indices are filtered and back-filled

- **GIVEN** prefilter path produced a 30-chunk candidate pool
- **AND** the Voyage rerank response includes indices outside `[0, 29]` (e.g., due to API contract drift)
- **WHEN** the tool collects the top `k=5` chunks
- **THEN** unknown indices SHALL be discarded
- **AND** the kept ordering SHALL follow valid indices in Voyage's order
- **AND** the gap (if fewer than `k` valid) SHALL be filled from the next chunk in original RRF order that is not already in the kept list
- **AND** the envelope's `rerank_applied` SHALL be `true`

<!-- @trace
source: retrieval-rerank-via-voyage
updated: 2026-05-27
code:
  - backend/app/services/chat_agent/tools.py
  - backend/app/services/rag_rerank.py
tests:
  - backend/tests/test_chat_agent_topic_prefilter_rerank.py
  - backend/tests/test_voyage_rerank.py
note: supersedes the LLM-as-reranker pipeline introduced (and disabled) by
      change retrieval-cross-episode-chunk-recovery. The envelope contract
      (rerank_applied, rerank_input_count) is reused intact.
-->
