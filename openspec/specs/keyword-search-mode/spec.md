# keyword-search-mode Specification

## Purpose

TBD - created by archiving change 'keyword-index-mode'. Update Purpose after archive.

## Requirements

### Requirement: Keyword search endpoint with strict AND semantics

The backend SHALL expose `POST /shows/{show_id}/keyword-search` that accepts `{ "query": str, "offset_t1": int = 0, "offset_t2": int = 0, "limit": int = 25 }` and returns sectioned results `t1`, `t2`, and `t3`. The endpoint SHALL tokenize `query` via `app.services.tokenizer.tokenize()`, drop punctuation-only and single-character stopword tokens, deduplicate preserving order, and treat the resulting `terms` list as the canonical search terms. The endpoint SHALL return HTTP 422 with error code `EMPTY_QUERY` when `terms` is empty after tokenization. The endpoint SHALL return HTTP 404 with error code `SHOW_NOT_FOUND` when `show_id` does not resolve to a `shows` row. The endpoint SHALL NOT parse quote phrase syntax, SHALL NOT parse an `OR` operator, and SHALL NOT parse exclusion (`-term`) syntax — all multi-term queries SHALL be combined with AND for `t1` and `t2`.

#### Scenario: Empty query after tokenization

- **WHEN** the client posts `{ "query": "！！！" }` and jieba tokenization yields no non-punctuation tokens
- **THEN** the endpoint SHALL respond 422 with `{ "error": { "code": "EMPTY_QUERY" } }` and SHALL NOT execute any database query against the search pools

#### Scenario: Multi-term AND enforcement

- **WHEN** the client posts `{ "query": "馬世芳 滅火器" }` against a show whose chunks contain only one of the two terms
- **THEN** `t1.items` SHALL be empty and `t2.items` SHALL only contain episodes where BOTH terms appear across the three pools

##### Example: AND vs OR distinction

- **GIVEN** an episode with title containing only "馬世芳" and transcript containing only "滅火器", and a separate episode with both terms present in transcript
- **WHEN** the client posts `{ "query": "馬世芳 滅火器" }`
- **THEN** the first episode SHALL appear in `t2` (cross-pool AND: title pool covers "馬世芳", transcript pool covers "滅火器"), the second episode SHALL appear in both `t1` (same-chunk AND) and `t2`


<!-- @trace
source: keyword-index-mode
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: T1 same-chunk AND section

The endpoint SHALL populate `t1.items` with `transcript_chunks` rows belonging to the requested `show_id` where `text_tsvector @@ to_tsquery('simple', :q_and)` is true and `:q_and` is the AND-joined jieba-escaped term list. Each `t1.items[i]` SHALL include `chunk_id`, `episode_id`, `episode_title`, `start_time`, `end_time`, `text`, and `hits` (per-term match positions). `t1.items` SHALL be ordered by `ts_rank(text_tsvector, :q_and)` descending and SHALL be limited to at most 100 items in total across paginated calls, with each individual call returning at most `limit` items starting at `offset_t1`. `t1.total` SHALL reflect the total number of matching chunks (capped at 100) regardless of pagination offset.

#### Scenario: T1 ordering by ts_rank

- **WHEN** three chunks in the same show match all query terms with `ts_rank` values 0.8, 0.4, and 0.6
- **THEN** `t1.items` SHALL list them in order rank 0.8, 0.6, 0.4

#### Scenario: T1 hard cap at 100

- **WHEN** 250 chunks match the AND query and the client paginates with `offset_t1=95, limit=25`
- **THEN** the endpoint SHALL return at most 5 items (cap 100 minus offset 95) and `t1.total` SHALL equal 100


<!-- @trace
source: keyword-index-mode
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: T2 cross-pool episode AND section

The endpoint SHALL populate `t2.items` with episodes belonging to the requested `show_id` where every term in `terms` is matched by at least one of the three pools: `episodes.title_tsvector`, `episode_description_chunks.text_tsvector`, or `transcript_chunks.text_tsvector`. An episode SHALL qualify if and only if for every `term` in `terms`, at least one of the three pools yields a `@@ to_tsquery('simple', term)` match for that episode. Each `t2.items[i]` SHALL include `episode_id`, `episode_title`, and `pool_counts` containing per-pool match counts under keys `title`, `description`, and `transcript`. `t2.items` SHALL be limited to at most 100 items in total across paginated calls.

#### Scenario: Cross-pool union satisfies all terms

- **WHEN** an episode has term A only in its title and term B only in its transcript chunks
- **THEN** the episode SHALL appear in `t2.items` with `pool_counts.title >= 1` and `pool_counts.transcript >= 1`

#### Scenario: Missing term in all pools excludes episode

- **WHEN** an episode has terms A and B present across pools but term C absent from all three pools
- **THEN** the episode SHALL NOT appear in `t2.items`


<!-- @trace
source: keyword-index-mode
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: T2 collapse threshold

The endpoint SHALL read the integer admin setting `keyword_t2_collapse_threshold` (default 10) on each request. When `t1.total >= keyword_t2_collapse_threshold`, the response SHALL set `t2.collapsed = true`; otherwise `t2.collapsed = false`. The `t2.items` array and `t2.total` SHALL be populated identically regardless of the `collapsed` flag — the flag is a presentation hint only, the backend SHALL NOT omit data based on it.

#### Scenario: T1 above threshold collapses T2 presentation flag

- **WHEN** the admin setting is 10 and `t1.total = 15`
- **THEN** `t2.collapsed` SHALL be `true` and `t2.items` SHALL still contain the full computed list

#### Scenario: T1 below threshold leaves T2 expanded

- **WHEN** the admin setting is 10 and `t1.total = 4`
- **THEN** `t2.collapsed` SHALL be `false`


<!-- @trace
source: keyword-index-mode
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: T3 OR fallback section

The endpoint SHALL compute and return `t3` only when `t1.total == 0` AND `t2.total == 0`. When triggered, `t3` SHALL contain up to 50 `transcript_chunks` belonging to the requested `show_id` where `text_tsvector @@ to_tsquery('simple', :q_or)` is true and `:q_or` is the OR-joined term list. When `t1.total > 0` or `t2.total > 0`, `t3` SHALL be `null` and the backend SHALL NOT execute the OR query.

#### Scenario: T3 suppressed when T1 has hits

- **WHEN** `t1.total = 3` and `t2.total = 0`
- **THEN** the response SHALL have `t3 == null` and the OR query SHALL NOT be executed

#### Scenario: T3 triggered on empty T1 and T2

- **WHEN** both `t1.total` and `t2.total` are 0 and at least one query term matches some chunk
- **THEN** `t3.items` SHALL contain at least one chunk and `t3.total` SHALL be ≤ 50


<!-- @trace
source: keyword-index-mode
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: Admin setting keyword_t2_collapse_threshold

The backend SHALL persist a settings row with key `keyword_t2_collapse_threshold` storing an integer with default value `10`. The existing admin settings GET and PUT endpoints SHALL expose this key for read and update. Changes to the value SHALL take effect on the next inbound `POST /shows/{show_id}/keyword-search` request without requiring a process restart.

#### Scenario: Admin updates threshold and next search reflects new value

- **WHEN** an admin updates `keyword_t2_collapse_threshold` from 10 to 3 and a subsequent keyword search returns `t1.total = 5`
- **THEN** the response SHALL have `t2.collapsed == true`


<!-- @trace
source: keyword-index-mode
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: Pagination contract

The endpoint SHALL accept `offset_t1` and `offset_t2` integer parameters (default 0, minimum 0) and a `limit` parameter (default 25, range 1..100). For each section, the returned `items` SHALL be the slice `[offset, offset + limit)` of the ordered result set, capped at the hard limit of 100 total per section. `t1.total` and `t2.total` SHALL reflect the cap-aware total (i.e., `min(actual_match_count, 100)`) so the client can detect end-of-section by comparing accumulated length with `total`.

#### Scenario: Client paginates T1 in chunks of 5

- **WHEN** 12 chunks match AND the client calls with `offset_t1=0, limit=5`, then `offset_t1=5, limit=5`, then `offset_t1=10, limit=5`
- **THEN** the three responses SHALL return 5, 5, and 2 items respectively, and `t1.total` SHALL be 12 in every response

<!-- @trace
source: keyword-index-mode
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: Keyword search consults the result cache and reports cache_hit

The keyword search endpoint SHALL consult the service-layer keyword result cache before running its three-stage SQL, and SHALL include a `cache_hit` boolean in its response. On a cache hit it SHALL return the cached T1/T2/T3 result without re-running SQL. On a miss it SHALL run normally and populate the cache. The cache key SHALL include the show id, corpus version, the normalized question, and the collapse threshold. Cache failures SHALL fall back to the normal SQL path without failing the request.

#### Scenario: Cache hit returns sectioned result without re-running SQL

- **GIVEN** an identical keyword query was previously cached for a show with unchanged corpus version
- **WHEN** the query is sent again
- **THEN** the response returns the same T1/T2/T3 sections and `cache_hit` is true

#### Scenario: Collapse threshold change invalidates the cached result

- **GIVEN** a keyword result is cached under the current collapse threshold
- **WHEN** an admin changes the keyword collapse threshold
- **THEN** the next identical keyword query misses the cache and reflects the new threshold

<!-- @trace
source: r4-rag-result-cache
updated: 2026-06-10
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
-->