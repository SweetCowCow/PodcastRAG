## MODIFIED Requirements

### Requirement: Recall@K and MRR are computed per query against ground-truth chunks

The eval framework SHALL provide retrieval metrics implemented in pure Python (numpy), dispatched per item by the `eval_mode` field declared on each golden-set item:

- **`eval_mode: "chunk_id"`** (legacy default for backward compatibility): the runner SHALL compute Recall@K and MRR against `ground_truth_chunk_ids`.
  - **Recall@K** (default K=5): `|relevant ∩ topK| / |relevant|` per query. Items with empty `ground_truth_chunk_ids` (e.g., `negative` type) SHALL be excluded from the per-query Recall mean.
  - **MRR**: `mean(1/rank_of_first_relevant)` where `rank` is 1-based; items where no relevant chunk appears SHALL contribute 0 to the mean.
- **`eval_mode: "open_set_lenient"`**: the runner SHALL compute per-item recall as `1.0` if any retrieved chunk identifier matches any entry in `ground_truth_chunk_ids` (after the lenient match window applied for chunk_id mode), otherwise `0.0`. These items SHALL aggregate together with `chunk_id` items in the chunk-based Recall group.
- **`eval_mode: "enumeration"`**: the runner SHALL ignore `ground_truth_chunk_ids` and instead compute `episode_set_recall = |retrieved_episode_set ∩ expected_episode_set| / |expected_episode_set|`, where `retrieved_episode_set` is the unique set of episode UUIDs across the top-K retrieved chunks and `expected_episode_set` comes from the item's `expected_episode_ids`. Enumeration items SHALL NOT appear in the chunk-based Recall@K mean; they SHALL aggregate into a separate `episode_set_recall_mean`.

All chunk-matching functions SHALL accept the canonical `ep:<episode_id>@<start_time>` format and SHALL match by string equality after `start_time` is rounded to 2 decimals.

The runner SHALL NOT impose pass/fail thresholds on `episode_set_recall`; it reports the raw fractional value per item and the mean across enumeration items, so trends can be tracked even when top-K caps the value below 1.0.

#### Scenario: Recall@5 with one of two ground-truth chunks in top-5

- **GIVEN** an item with `eval_mode: "chunk_id"` and `ground_truth_chunk_ids = ["ep:a@1.00", "ep:b@2.00"]`
- **WHEN** the runner returns top-5 chunks `["ep:c@0.50", "ep:a@1.00", "ep:d@3.00", "ep:e@4.00", "ep:f@5.00"]`
- **THEN** `recall@5` for this item SHALL be `0.5`

#### Scenario: MRR with first relevant at rank 2

- **GIVEN** an item with `eval_mode: "chunk_id"` whose first relevant chunk appears at top-list index 1 (rank 2)
- **WHEN** MRR is computed for a single-item set
- **THEN** the MRR value SHALL be `0.5`

#### Scenario: Negative items excluded from recall mean

- **GIVEN** a dataset containing 4 items with `eval_mode: "chunk_id"` (all top-5 hit) and 1 negative item with `eval_mode: "chunk_id"` + empty `ground_truth_chunk_ids`
- **WHEN** chunk-based Recall@5 is averaged
- **THEN** the result SHALL be `1.0` (negative item excluded from denominator)

##### Example: 3-item chunk-based recall computation

| Item   | eval_mode | ground_truth                   | top5 returned                                | per-item recall |
| ------ | --------- | ------------------------------ | -------------------------------------------- | --------------- |
| q1     | chunk_id  | `["ep:a@1.00"]`                | `["ep:a@1.00", ...]`                         | 1.0             |
| q2     | chunk_id  | `["ep:b@2.00", "ep:c@3.00"]`   | `["ep:x@9.00", "ep:b@2.00", ...]`            | 0.5             |
| q3 neg | chunk_id  | `[]`                           | `[...]`                                      | excluded        |

- **GIVEN** the table above
- **WHEN** the runner computes chunk-based Recall@5
- **THEN** the reported recall SHALL be `0.75`

#### Scenario: Open-set lenient mode treats any-anchor-hit as 1.0

- **GIVEN** an item with `eval_mode: "open_set_lenient"` and `ground_truth_chunk_ids = ["ep:a@100.00", "ep:a@200.00", "ep:b@50.00"]`
- **WHEN** the runner returns top-5 chunks where exactly one chunk matches `ep:a@200.00` (within the lenient window)
- **THEN** per-item recall SHALL be `1.0` (not the fractional `1/3` that chunk_id mode would produce)

#### Scenario: Enumeration mode computes episode-set recall

- **GIVEN** an item with `eval_mode: "enumeration"` and `expected_episode_ids = ["ep-A", "ep-B", "ep-C", "ep-D", "ep-E"]` (5 episodes)
- **WHEN** the runner returns top-5 chunks spanning episodes `{ep-A, ep-A, ep-C, ep-X, ep-Y}` (unique set `{ep-A, ep-C, ep-X, ep-Y}`)
- **THEN** `episode_set_recall` for this item SHALL be `0.4` (2 of 5 expected episodes covered)

##### Example: top_k=5 ceiling on large expected sets

- **GIVEN** an enumeration item with `expected_episode_ids` containing 25 episodes
- **WHEN** the runner runs with `top_k=5` and retrieves 5 chunks all from distinct expected episodes
- **THEN** `episode_set_recall` SHALL equal `0.20` (the structural ceiling at top_k=5; this is a known limitation tracked for the future `eval-runner-dynamic-top-k` change)

#### Scenario: Aggregate report separates chunk-based and enumeration metrics

- **GIVEN** a dataset with 28 items in `chunk_id`/`open_set_lenient` mode and 2 items in `enumeration` mode
- **WHEN** the runner completes a full eval pass
- **THEN** the report JSON SHALL contain `metrics.chunk_based.recall_at_k_mean` aggregating only the 28 non-enumeration items
- **AND** `metrics.enumeration.episode_set_recall_mean` aggregating only the 2 enumeration items
- **AND** the markdown report SHALL render two separate rows: one labeled `(chunk, n=28)` and one labeled `(enumeration, n=2)`
- **AND** no single "overall recall" cell SHALL mix the two metric families

#### Scenario: Enumeration items do not pollute chunk-based mean

- **GIVEN** a single enumeration item with `episode_set_recall = 0.20` mixed into a dataset of 4 chunk-based items each scoring `recall@5 = 1.0`
- **WHEN** the runner aggregates
- **THEN** `metrics.chunk_based.recall_at_k_mean` SHALL be `1.0` (enumeration excluded)
- **AND** `metrics.enumeration.episode_set_recall_mean` SHALL be `0.20`

#### Scenario: Per-item record carries eval_mode and episode_set_recall

- **GIVEN** an enumeration item completes evaluation
- **WHEN** the runner writes the per-item result record to disk
- **THEN** the record SHALL include `eval_mode: "enumeration"` and `episode_set_recall: <float>`
- **AND** for a `chunk_id` item the record SHALL include `eval_mode: "chunk_id"` and SHALL omit `episode_set_recall` (or set it to null)
