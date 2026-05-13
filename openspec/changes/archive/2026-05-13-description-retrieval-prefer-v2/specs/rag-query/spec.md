## MODIFIED Requirements

### Requirement: `retrieve_hybrid` prefers v2 description chunks per-episode, falls back to v1

The description-side hybrid retrieval SQL (`_DESC_RRF_SQL` and `_DESC_SEMANTIC_ONLY_SQL` in `backend/app/services/rag.py`) SHALL implement a **prefer-v2** policy per episode: for any episode that has at least one `chunking_version = 2` row in the queried show, **only** v2 rows of that episode SHALL enter the retrieval pool (both semantic and lexical CTE). For episodes without any v2 rows, v1 rows SHALL fall back into the pool.

This MODIFIES the previous requirement (from `chunking-version-coexistence` D3) that said retrieval SHALL NOT filter rows by `chunking_version`. The previous "v1+v2 share one RRF pool, RRF score decides" assumption was falsified by `r3-2-retrieval-fix` Phase 2 final eval (Recall@5 退步 0.1548 → 0.0952). Root cause: PG `ts_rank` systematically scores short chunks lower than long chunks for single-token-match queries, and v1 long rows flood the `RRF_PER_SIDE = 50` cap, evicting v2 short rows from the lexical CTE entirely. See `docs/case-studies/r32-routing-regression-2026-05-11.md` 2026-05-12 下午 section.

#### Scenario: Same-episode v2 hides v1 from pool

- **GIVEN** an episode E in show S has both v1 and v2 description chunks
- **WHEN** `retrieve_descriptions(show_id=S, ...)` is called
- **THEN** the result hits for episode E SHALL all have `chunking_version = 2`
- **AND** no v1 hit from episode E SHALL appear in the result

#### Scenario: Episode without v2 falls back to v1

- **GIVEN** an episode E2 in show S has only v1 description chunks (no v2 rows)
- **AND** another episode E1 in the same show has v2 chunks
- **WHEN** `retrieve_descriptions(show_id=S, ...)` is called
- **THEN** the result MAY include `chunking_version = 1` hits from E2
- **AND** the result for E1 SHALL only contain `chunking_version = 2` hits

#### Scenario: Show without any v2 chunks degenerates to pure-v1 pool

- **GIVEN** a show S has zero v2 chunks across all its episodes
- **WHEN** `retrieve_descriptions(show_id=S, ...)` is called
- **THEN** the result SHALL behave identically to the pre-`chunking-version-coexistence` baseline (all hits `chunking_version = 1`)

## ADDED Requirements

### Requirement: `route_episodes` returns distinct episode_ids and prefers v2 ranking

`_ROUTE_EPISODES_SQL` (the first-layer two-layer routing query in `backend/app/services/rag.py`) SHALL return at most `k` **distinct** episode_ids, not `k` chunk-row results. For each candidate episode, its representative cosine distance SHALL be computed from the episode's v2 chunks if it has any, falling back to v1 otherwise (same prefer-v2 policy as retrieval).

The previous SQL `SELECT e.id ... ORDER BY d.embedding <=> :qv LIMIT :k` returned chunk-row level results, which after v1+v2 coexistence (~16× pool growth) caused 4-5 episodes' chunks to consume the top-10 budget, hard-filtering retrieval to the wrong episode set. See case study root cause #3.

#### Scenario: Routing returns k distinct episode_ids

- **GIVEN** a show has 10 v2 chunks for episode E1 and 1 v1 chunk for E2 (only)
- **WHEN** `route_episodes(show_id, query_embedding, k=2)` is called
- **THEN** the result SHALL contain exactly 2 elements: `[E1.id, E2.id]` (in any order)
- **AND** the result SHALL NOT contain duplicate episode_ids

#### Scenario: Routing prefers v2 chunks for ranking when present

- **GIVEN** episode E has both v1 and v2 chunks
- **WHEN** routing computes E's cosine distance for ranking purposes
- **THEN** the distance SHALL be the minimum cosine distance over E's v2 chunks
- **AND** E's v1 chunks SHALL NOT influence the distance value

#### Scenario: Routing falls back to v1 when episode has no v2

- **GIVEN** episode E has only v1 chunks (no v2)
- **AND** another episode in the same show has v2 chunks
- **WHEN** routing computes ranking
- **THEN** E SHALL still be eligible for top-K via its v1 chunk's cosine distance

### Requirement: prefer-v2 SQL uses PG-friendly semi-join form

The prefer-v2 WHERE clause in `_DESC_RRF_SQL`, `_DESC_SEMANTIC_ONLY_SQL`, and `_ROUTE_EPISODES_SQL` SHALL be written such that the PostgreSQL planner uses a hash semi-join (not a per-row nested loop subquery) for the "episodes-with-v2" sub-select. The implementation SHALL verify this via `EXPLAIN ANALYZE` against the pilot show before deploying.

#### Scenario: EXPLAIN ANALYZE shows hash semi-join

- **GIVEN** the modified retrieval SQL is run against a show with mixed v1/v2 chunks
- **WHEN** `EXPLAIN ANALYZE SELECT ... FROM ...` is captured locally
- **THEN** the plan SHALL include a `Hash Semi Join` or `Hash Anti Join` node (or equivalent)
- **AND** SHALL NOT include a `SubPlan` that re-executes per outer row
