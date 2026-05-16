## MODIFIED Requirements

### Requirement: Recall@K and MRR are computed per query against ground-truth chunks

For each item the runner SHALL:

1. Call the public search endpoint (`POST /shows/{id}/search`) and retrieve the top-K chunks.
2. Dispatch the per-item recall calculation on `eval_mode`:

- **`eval_mode: "chunk_id"`** (default when field is absent): the runner SHALL compute Recall@K and Reciprocal Rank against `ground_truth_chunk_ids`. The chunk identifier match SHALL be either exact (`metric_level=chunk`, default 10s window via `--match-window-s`) or episode-level (`metric_level=episode`, any chunk from the same episode counts).
- **`eval_mode: "open_set_lenient"`**: the runner SHALL compute per-item recall as `1.0` if any retrieved chunk identifier matches any entry in `ground_truth_chunk_ids` (after the lenient match window applied for chunk_id mode), otherwise `0.0`. These items SHALL aggregate together with `chunk_id` items in the chunk-based Recall group.
- **`eval_mode: "enumeration"`**: the runner SHALL ignore `ground_truth_chunk_ids` and instead compute `episode_set_recall = |retrieved_episode_set ∩ expected_episode_set| / |expected_episode_set|`. `retrieved_episode_set` SHALL be the UNION of two sources: (a) the unique episode UUIDs across the top-K chunks returned by the search endpoint, AND (b) the unique episode UUIDs from `enumeration_episodes` returned by an additional chat endpoint call (`POST /shows/{id}/query` with `mode: "chat"`). `expected_episode_set` comes from the item's `expected_episode_ids`. Enumeration items SHALL NOT appear in the chunk-based Recall@K mean; they SHALL aggregate into a separate `episode_set_recall_mean`.

All chunk-matching functions SHALL accept the canonical `ep:<episode_id>@<start_time>` format and SHALL match by string equality after `start_time` is rounded to 2 decimals.

The runner SHALL NOT impose pass/fail thresholds on `episode_set_recall`; it reports the raw fractional value per item and the mean across enumeration items, so trends can be tracked.

The runner SHALL only invoke the chat endpoint for items whose `eval_mode == "enumeration"`. Items in `chunk_id` or `open_set_lenient` mode SHALL NOT trigger a chat-endpoint call, preserving their existing search-only retrieval cost profile.

#### Scenario: Recall@5 with one of two ground-truth chunks in top-5

- **GIVEN** an item with `eval_mode: "chunk_id"` and `ground_truth_chunk_ids = ["ep:a@1.00", "ep:b@2.00"]`
- **WHEN** the runner returns top-5 chunks `["ep:c@0.50", "ep:a@1.00", "ep:d@3.00", "ep:e@4.00", "ep:f@5.00"]`
- **THEN** the item's `recall_at_k` SHALL be `0.5` (1 of 2 matched)
- **AND** the item's `reciprocal_rank` SHALL be `0.5` (1 / 2, since `ep:a@1.00` appeared at rank 2)

#### Scenario: Enumeration recall counts both search and chat hits

- **GIVEN** an item with `eval_mode: "enumeration"` and `expected_episode_ids = ["ep-A", "ep-B", "ep-C", "ep-D", "ep-E"]`
- **AND** the search endpoint top-K=5 returns chunks whose episode_ids are `{"ep-A", "ep-X"}` (1 hit)
- **AND** the chat endpoint's `enumeration_episodes` returns episode_ids `{"ep-A", "ep-B", "ep-C", "ep-D"}` (4 hits, overlapping with search on `ep-A`)
- **WHEN** the runner scores this item
- **THEN** `retrieved_episode_set` SHALL equal `{"ep-A", "ep-B", "ep-C", "ep-D", "ep-X"}` (union, deduplicated)
- **AND** `episode_set_recall` SHALL equal `0.8` (4 of 5 expected episodes covered)

#### Scenario: Top-K=5 structural ceiling is removed when chat-path enumeration is large

- **GIVEN** an enumeration item with `expected_episode_ids` containing 25 episodes
- **AND** the chat endpoint's `enumeration_episodes` returns 23 of those 25 (no backend cap on enumeration)
- **WHEN** the runner scores this item with `top_k = 5` (search side capped, chat side uncapped)
- **THEN** `episode_set_recall` SHALL equal `0.92` (the prior structural ceiling at top_k=5 from search-only scoring no longer applies)

#### Scenario: Aggregate report separates chunk-based and enumeration metrics

- **GIVEN** a dataset with 28 items in `chunk_id`/`open_set_lenient` mode and 2 items in `enumeration` mode
- **WHEN** the runner completes a full eval pass
- **THEN** the report JSON SHALL contain `metrics.chunk_based.recall_at_k_mean` aggregating only the 28 non-enumeration items
- **AND** `metrics.enumeration.episode_set_recall_mean` aggregating only the 2 enumeration items
- **AND** the markdown report SHALL render two separate rows: one labeled `(chunk, n=28)` and one labeled `(enumeration, n=2)`

#### Scenario: Non-enumeration items skip the chat endpoint call

- **GIVEN** items with `eval_mode: "chunk_id"` and items with `eval_mode: "open_set_lenient"` in the dataset
- **WHEN** the runner processes them
- **THEN** the runner SHALL NOT issue any `POST /shows/{id}/query` call for these items
- **AND** their retrieval cost SHALL be identical to runs before this change shipped

## ADDED Requirements

### Requirement: Enumeration items carry chat-side diagnostic fields in per-item JSON output

Each item in the report JSON's `items` array whose `eval_mode == "enumeration"` SHALL carry two additional fields beyond the existing `episode_set_recall` value:

- `enumeration_episodes_count: int` — the length of the `enumeration_episodes` list returned by the chat endpoint (0 when the chat call failed or returned `null`).
- `episode_set_recall_chat_only: float | None` — the `episode_set_recall` value computed using ONLY the chat-side episode_ids (no union with search). `None` when the chat call failed; `0.0` when the call succeeded but matched zero expected episodes.

These diagnostic fields enable RCA when search-side and chat-side paths diverge — without them, a future regression in either path would be invisible in the union-only number.

#### Scenario: Per-item JSON includes chat diagnostic fields

- **GIVEN** an enumeration item where chat returned 23 episodes and search returned 1 unique episode
- **WHEN** the runner writes the report
- **THEN** the item record SHALL contain `enumeration_episodes_count: 23`
- **AND** `episode_set_recall_chat_only` SHALL be the fraction `|chat_episode_set ∩ expected_episode_set| / |expected_episode_set|` (computed from the 23 chat episodes only)

### Requirement: Chat endpoint failures fail-open with empty episode set

The chat endpoint call from the runner's enumeration scoring path SHALL NOT abort the eval run on any failure mode. The helper SHALL catch every exception (network timeout, HTTP 5xx, missing CSRF token, malformed JSON, missing `enumeration_episodes` field) and return an empty episode list. The runner SHALL log the failure to stderr but continue processing the next item.

#### Scenario: Chat endpoint returns 5xx — runner continues

- **GIVEN** an enumeration item whose chat endpoint call returns HTTP 503
- **WHEN** the runner scores the item
- **THEN** the chat-side episode_id list SHALL be treated as empty
- **AND** `retrieved_episode_set` SHALL be just the search-side episode_ids (degenerate to the prior behavior)
- **AND** `enumeration_episodes_count` SHALL be `0` in the per-item JSON
- **AND** `episode_set_recall_chat_only` SHALL be `None`
- **AND** the runner SHALL log a warning to stderr identifying the item id and HTTP status
- **AND** the runner SHALL continue to the next item without raising

#### Scenario: Chat endpoint requires CSRF token but session has none — fail open

- **GIVEN** the configured `--auth-token` session does not produce a `csrf_token` value via `/me`
- **WHEN** the runner attempts the chat call for an enumeration item
- **THEN** the helper SHALL skip the call and treat the response as empty
- **AND** the runner SHALL log a single warning at startup (not per-item) identifying that chat scoring is disabled for this run
- **AND** subsequent enumeration items SHALL fall back to search-only scoring (degenerate to the prior behavior)

#### Scenario: Chat response missing enumeration_episodes field — fail open

- **GIVEN** a chat endpoint response whose JSON body lacks `enumeration_episodes` (the chat path classified the question as non-enumeration)
- **WHEN** the runner reads the response
- **THEN** the chat-side episode_id list SHALL be treated as empty (this is the expected case when an enumeration-mode test item happens to use a question that the chat path does NOT classify as enumeration — surfaces a dataset/path mismatch worth investigating)
- **AND** `enumeration_episodes_count` SHALL be `0`
- **AND** `episode_set_recall_chat_only` SHALL be `0.0` (not None — the call succeeded but matched zero expected episodes)
