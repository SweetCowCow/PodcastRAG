# chat-agentic-routing Delta

## MODIFIED Requirements

### Requirement: search_with_topic_prefilter SHALL pre-scope retrieval to topic-matching episodes

The `search_with_topic_prefilter(topic: str, query: str, k: int = 5)` tool SHALL execute the following retrieval pipeline:

1. Call `episode_finders.find_episodes_by_topic(show_id, [topic])` to obtain a candidate episode list `candidates`.
2. If `len(candidates) > 0`, call `rag.retrieve_hybrid(query, episode_id_filter=[ep.episode_id for ep in candidates], k=k)`.
3. If `len(candidates) == 0`, fall back to `rag.retrieve_hybrid(query, k=k)` without filter so the caller still receives chunks (degraded gracefully, equivalent to `search_across_episodes`).

The tool result envelope SHALL include:

- `chunks`: same shape as other search tools (list of dicts via `_chunk_to_dict`)
- `prefilter_episode_count`: integer, the size of `candidates` returned by the topic finder
- `fallback_to_full_pool`: boolean, `true` when step 3 (empty-candidate fallback) was taken, `false` when step 2 ran
- `rerank_applied`: boolean reserved for the follow-up rerank change. In the current shipped behavior this SHALL always be `false`.
- `rerank_input_count`: integer reserved for the follow-up rerank change. In the current shipped behavior this SHALL always be `0`.

The `rerank_applied` and `rerank_input_count` envelope fields exist to provide a stable contract for the follow-up `retrieval-rerank-via-voyage` change (or equivalent) to swap a rerank stage in without re-touching downstream consumers. LLM-as-reranker via Zeabur AI Hub was attempted and proved non-viable in this change (see case study `docs/case-studies/retrieval-cross-episode-chunk-recovery-2026-05-26.md`); the wrapper `app.services.rag_rerank.llm_rerank` is left in the repository for direct reuse by the follow-up.

#### Scenario: Topic match returns candidates, retrieval is scoped to them

- **GIVEN** the show contains episodes EP143, EP107, EP66 whose `find_episodes_by_topic(topic="家常味")` returns `[EP143, EP107]`
- **AND** the LLM calls `search_with_topic_prefilter(topic="家常味", query="馬世芳怎麼定義家常味", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL pass `episode_id_filter=[EP143_uuid, EP107_uuid]` and `k=5`
- **AND** the returned envelope's `prefilter_episode_count` SHALL equal `2`
- **AND** the envelope's `fallback_to_full_pool` SHALL be `false`
- **AND** the envelope's `rerank_applied` SHALL be `false` (rerank stage not active in this change)
- **AND** the envelope's `rerank_input_count` SHALL be `0`
- **AND** no returned chunk SHALL have an `episode_id` outside `{EP143_uuid, EP107_uuid}`

#### Scenario: No topic match falls back to full-show retrieval without filter

- **GIVEN** `find_episodes_by_topic(topic="lorem-ipsum-no-match")` returns an empty list
- **AND** the LLM calls `search_with_topic_prefilter(topic="lorem-ipsum-no-match", query="any question", k=5)`
- **WHEN** the tool dispatcher executes
- **THEN** the underlying `rag.retrieve_hybrid` call SHALL be invoked WITHOUT an `episode_id_filter` (full show pool) and with `k=5`
- **AND** the returned envelope's `prefilter_episode_count` SHALL equal `0`
- **AND** the envelope's `fallback_to_full_pool` SHALL be `true`
- **AND** the envelope's `rerank_applied` SHALL be `false`
- **AND** the envelope's `rerank_input_count` SHALL be `0`
- **AND** `chunks` MAY contain up to `k` results spanning any episode

#### Scenario: Envelope fields are always populated

- **GIVEN** any successful invocation of `search_with_topic_prefilter`
- **WHEN** the tool dispatcher records the result
- **THEN** the envelope SHALL contain the keys `chunks`, `prefilter_episode_count`, `fallback_to_full_pool`, `rerank_applied`, and `rerank_input_count` regardless of whether the prefilter path or fallback path executed
- **AND** the chunk dict shape SHALL be identical to that returned by `search_across_episodes` and `search_in_episodes` (so downstream `_collect_agentic_citations` does not need branching)

#### Scenario: Tool description guides LLM away from search_across_episodes for topical questions

- **GIVEN** the OpenAI tool schema generated from `SearchWithTopicPrefilterInput`
- **WHEN** the schema is rendered to the LLM
- **THEN** the description string SHALL explicitly recommend this tool over `search_across_episodes` for questions that name a topic / theme spanning multiple episodes
- **AND** the `search_across_episodes` tool description SHALL be updated to call itself the "fallback" path and refer the LLM to `search_with_topic_prefilter` for topical cross-episode queries

<!-- @trace
source: retrieval-cross-episode-chunk-recovery
updated: 2026-05-27
code:
  - backend/app/services/chat_agent/tools.py
  - backend/app/services/rag_rerank.py
tests:
  - backend/tests/test_chat_agent_topic_prefilter_rerank.py
  - backend/tests/test_rerank.py
note: rerank stage left disabled in this change; envelope contract reserves
      `rerank_applied` / `rerank_input_count` for the follow-up
      `retrieval-rerank-via-voyage` change.
-->
