## ADDED Requirements

### Requirement: Two-layer retrieval — first-layer episode routing

The retrieval pipeline SHALL contain a first-layer routing step `route_episodes(db, show_id, query_embedding, k=10)` that returns the top-`k` `episode_id` values for the query, ranked solely by cosine similarity between `query_embedding` and `episode_description_chunks.embedding`. The routing SHALL JOIN through `episodes` to enforce the `show_id` filter and SHALL exclude episodes whose description chunk is missing.

The default `k` SHALL be 10. Routing SHALL be skipped when the question text yields fewer than 2 jieba tokens of length ≥ 2 (entity-only or single-word queries) — in that case the second-layer hybrid retrieval SHALL run against the full show without an episode filter.

#### Scenario: Top-10 episodes returned by description cosine

- **GIVEN** a show with 162 episodes each carrying a non-null `episode_description_chunks` row
- **WHEN** `route_episodes(db, show_id, query_embedding, k=10)` is called
- **THEN** exactly 10 `episode_id` values SHALL be returned
- **AND** the values SHALL be ordered by ascending cosine distance to `query_embedding`

#### Scenario: Skip routing for entity-only short query

- **GIVEN** a question containing only one jieba token of length ≥ 2 (e.g. just "迪拉胖")
- **WHEN** the search endpoint runs
- **THEN** routing SHALL NOT be invoked
- **AND** the second-layer hybrid retrieval SHALL run against the entire show

#### Scenario: Routing limited by show

- **WHEN** routing is invoked for `show_id=A` while another show `B` has higher-similarity descriptions
- **THEN** the returned `episode_id` list SHALL contain only episodes whose `episodes.show_id = A`

### Requirement: Two-layer retrieval — second-layer episode-filtered hybrid

`retrieve_hybrid(db, show_id, query_embedding, question, k=8, episode_id_filter=None)` SHALL accept an optional `episode_id_filter: list[UUID] | None` parameter. When provided and non-empty, both the transcript-side and description-side CTEs SHALL include `episode_id IN :episode_id_filter` in their `WHERE` clauses (joining through `episodes` for transcript_chunks).

When `episode_id_filter` is `None` or empty, the function SHALL behave identically to its R3.1 form (search across the entire show).

#### Scenario: Filter restricts both sides

- **GIVEN** `episode_id_filter = [E1, E2, E3]`
- **WHEN** `retrieve_hybrid` is called
- **THEN** every result SHALL belong to one of `{E1, E2, E3}`
- **AND** transcript chunks from other episodes SHALL NOT appear even if their semantic distance is lower

#### Scenario: None filter falls back to full show

- **WHEN** `retrieve_hybrid(...)` is called with `episode_id_filter=None`
- **THEN** the SQL SHALL omit the `episode_id IN ...` predicate
- **AND** the result set SHALL be identical to R3.1 behaviour

### Requirement: Description hits capped in top-K

The merge step inside `retrieve_hybrid` SHALL cap the number of `source='description'` hits in the returned top-K to at most `DESCRIPTION_CAP` (a named constant in `backend/app/services/rag.py`). The cap SHALL default to 3. Excess description hits SHALL be replaced (in rank order) by the next-best transcript hits if any are available; if no transcript replacements remain, the description hits SHALL be returned to fill the slot.

#### Scenario: Cap of 3 description hits

- **GIVEN** RRF-merged ranking yields 5 description hits before any transcript hit
- **WHEN** the function returns top-K=8
- **THEN** the result SHALL contain at most 3 description hits
- **AND** at least 5 transcript hits if that many exist post-merge

#### Scenario: Cap waived when transcript pool is exhausted

- **GIVEN** RRF-merged ranking yields 4 description hits and 0 transcript hits (e.g. show with empty transcript_chunks)
- **WHEN** the function returns top-K=8
- **THEN** the result MAY contain all 4 description hits even though that exceeds `DESCRIPTION_CAP`

##### Example: Cap behaviour

| RRF order | source | included in top-8? |
| --- | --- | --- |
| 1 | description | yes (1/3) |
| 2 | description | yes (2/3) |
| 3 | description | yes (3/3) |
| 4 | description | no (cap hit) |
| 5 | transcript | yes |
| 6 | description | no |
| 7 | transcript | yes |
| 8 | transcript | yes |

## MODIFIED Requirements

### Requirement: Chat endpoint answers with citations using Tier 2 RAG

The backend SHALL expose `POST /shows/{show_id}/query` guarded by `require_authenticated_user` and atomic quota decrement (see user-quota). The endpoint SHALL execute the Tier 2 RAG pipeline: (1) if the request includes a non-empty `messages` history, rewrite the question to a standalone form using the configured rewrite model; (2) embed the (rewritten) question AND jieba-tokenise it; (3) **invoke `route_episodes()` to obtain a top-10 episode filter (skipping routing for short queries per the routing-skip rule)**; (4) retrieve top 8 results via `retrieve_hybrid()` with the episode filter and the `DESCRIPTION_CAP` mix; (5) generate an answer using the configured answer model with the retrieved chunks as grounding, requesting structured JSON output containing `answer` and `used_chunk_ids`; (6) return the answer together with only the citation chunks referenced in `used_chunk_ids`. Description-source citations SHALL be presented to the answer model with a clear marker (e.g. `desc:<episode_id>`) distinguishing them from transcript citations (`ep:<episode_id>@<start_time>`). If JSON parsing of the model output fails, the endpoint SHALL fall back to returning the raw text as `answer` with all retrieved chunks as `citations`. This endpoint SHALL NOT accept anonymous callers and SHALL NOT consult the IP rate limit.

#### Scenario: First turn skips rewrite but uses two-layer retrieval

- **WHEN** a client calls `POST /shows/{show_id}/query` with an empty or missing `messages` array
- **THEN** the endpoint SHALL NOT call the rewrite model, SHALL embed the original `question` directly, SHALL invoke `route_episodes()` then `retrieve_hybrid()` with the routing result as filter, and SHALL return an answer

#### Scenario: Follow-up turn rewrites and re-routes

- **WHEN** a client calls with non-empty `messages` history and a follow-up `question`
- **THEN** the endpoint SHALL call the rewrite model, embed the rewrite, invoke `route_episodes()` with the rewritten embedding, then `retrieve_hybrid()` with that filter

#### Scenario: Hybrid retrieval result feeds answer prompt

- **WHEN** a chat-mode query yields 5 transcript chunks and 3 description chunks (post-cap)
- **THEN** the answer prompt SHALL list all 8 results with `ep:<episode_id>@<start_time>` and `desc:<episode_id>` prefixes respectively

#### Scenario: Response includes only used citations

- **WHEN** chat mode completes successfully and the model returns valid JSON with `used_chunk_ids`
- **THEN** the response body SHALL contain `answer` and `citations` (chunks whose key appears in `used_chunk_ids`)

#### Scenario: Structured output parse failure falls back to full citations

- **WHEN** the answer model returns output that cannot be parsed as JSON or lacks `answer`
- **THEN** the endpoint SHALL return the raw text as `answer` and all retrieved chunks as `citations`

#### Scenario: Anonymous request rejected with 401

- **WHEN** an unauthenticated request reaches `POST /shows/{show_id}/query`
- **THEN** the response SHALL be HTTP 401

### Requirement: Semantic search endpoint returns ranked chunks

The backend SHALL expose `POST /shows/{show_id}/search` guarded by `optional_auth_with_ip_limit`. The endpoint accepts body `{"question": "<non-empty string>", "k": <optional int 1-50, default 8>}`. The endpoint SHALL embed the question, jieba-tokenise it, **invoke `route_episodes()` (with skip rule for short queries)**, and run `retrieve_hybrid()` with the routed `episode_id_filter`. Each result SHALL carry a `source` discriminator equal to `"transcript"` or `"description"`. The endpoint SHALL NOT include any LLM-generated answer. The endpoint SHALL NOT decrement `quota_remaining` even for authenticated callers. The `DESCRIPTION_CAP` rule SHALL apply.

#### Scenario: Anonymous request returns top-K with capped description mix

- **GIVEN** an unauthenticated visitor under the IP daily limit and a question yielding ≥ 2 multi-char jieba tokens
- **WHEN** the visitor calls `POST /shows/{show_id}/search`
- **THEN** routing SHALL run, hybrid retrieval SHALL apply the episode filter
- **AND** the result SHALL contain at most 3 description hits within the returned 8

#### Scenario: Short-query bypass for entity-only queries

- **GIVEN** a question whose jieba tokenisation yields < 2 tokens of length ≥ 2 (e.g. just "迪拉胖")
- **WHEN** the search endpoint runs
- **THEN** routing SHALL be skipped
- **AND** `retrieve_hybrid()` SHALL run with `episode_id_filter=None`

#### Scenario: Search excludes other shows after routing

- **WHEN** routing returns 10 `episode_id` for `show_id=A` and the second-layer query is issued
- **THEN** the response SHALL NOT include any chunk whose owning episode belongs to `show_id=B`, regardless of similarity

#### Scenario: Anonymous request over rate limit is rejected without embedding call

- **GIVEN** an unauthenticated visitor whose IP counter is at the daily limit
- **WHEN** the visitor calls `POST /shows/{show_id}/search`
- **THEN** the response SHALL be HTTP 429
- **AND** no embedding API call SHALL be made

### Requirement: Eval runner supports configurable metric level

The eval runner CLI (`backend/eval/runners/run.py`) SHALL accept a flag `--metric-level {episode,chunk}` with default value `episode`. Behaviour:

- `--metric-level=episode`: a retrieved chunk counts as a hit if its `episode_id` matches any anchor's `episode_id`. The `--match-window-s` flag is ignored in this mode.
- `--metric-level=chunk`: existing R1.2 / R3.1 behaviour — buckets `(episode_id, start_time // window_s)` for set-equality matching.

The output JSON SHALL include `metric_level` in the report's top-level fields. The summary markdown SHALL prefix the `Recall@K` row label with the metric level (e.g. `Recall@5 (episode)` vs `Recall@5 (chunk)`) so cross-run comparison is unambiguous.

#### Scenario: Episode mode counts cross-source hit

- **GIVEN** an anchor `ep:<E1>@252.60` (transcript chunk)
- **WHEN** retrieval returns a description chunk `ep:<E1>@0.00` (same episode, different source)
- **AND** runner is invoked with `--metric-level=episode`
- **THEN** the item's `recall_at_k` SHALL be 1.0

#### Scenario: Chunk mode behaviour preserved

- **GIVEN** the same anchor and retrieved chunk as above
- **WHEN** runner is invoked with `--metric-level=chunk` (default window 10s)
- **THEN** the item's `recall_at_k` SHALL be 0.0 (R3.1 behaviour preserved for legacy comparability)

#### Scenario: Markdown summary disambiguates metric level

- **WHEN** the runner finishes any run
- **THEN** the summary file SHALL contain a row whose label includes `(episode)` or `(chunk)` consistent with `metric_level`
