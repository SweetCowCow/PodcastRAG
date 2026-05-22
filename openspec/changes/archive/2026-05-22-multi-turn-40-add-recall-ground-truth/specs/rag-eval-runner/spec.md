## ADDED Requirements

### Requirement: Nested-schema eval path SHALL compute Recall@K when turn carries ground_truth_chunk_ids

When `run_chat_agent_eval.py` runs against a dataset whose items use the nested-multi-turn schema (`items[].turns[]` shape), the runner SHALL compute Recall@K per turn whenever that turn's `ground_truth_chunk_ids` is a non-null list. Computation SHALL use the existing `_recall_at_k(retrieved, ground_truth, k)` helper and the `/shows/{id}/search` endpoint with the turn's `question` and the runner's `--top-k`. Per-turn results SHALL gain a `recall_at_k` field (float or null). The aggregate object SHALL include `recall_at_k_mean` (mean across turns where `recall_at_k is not None`) and `n_scored_recall` (count of those turns); both SHALL be `null` / `0` when no turn in the dataset carries chunk-level ground truth, preserving the prior behavior for unannotated datasets.

#### Scenario: Turn with ground_truth_chunk_ids gets recall_at_k

- **GIVEN** a nested-schema dataset where turn `b01` carries `ground_truth_chunk_ids: ["ep:abc@10.0"]`
- **WHEN** `run_chat_agent_eval.py` processes that turn
- **THEN** the per-turn result SHALL include a numeric `recall_at_k` value in `[0.0, 1.0]`
- **AND** the turn SHALL be counted in `aggregate.n_scored_recall`

#### Scenario: Turn with null ground_truth_chunk_ids is skipped

- **GIVEN** a nested-schema turn where `ground_truth_chunk_ids` is `null` (e.g. multi-turn t2 ordinal reference)
- **WHEN** `run_chat_agent_eval.py` processes that turn
- **THEN** the per-turn result's `recall_at_k` SHALL be `null`
- **AND** the turn SHALL NOT be counted in `aggregate.n_scored_recall`

#### Scenario: Aggregate degrades cleanly for unannotated datasets

- **GIVEN** a nested-schema dataset where every turn has `ground_truth_chunk_ids: null`
- **WHEN** `run_chat_agent_eval.py` finishes
- **THEN** `aggregate.recall_at_k_mean` SHALL be `null`
- **AND** `aggregate.n_scored_recall` SHALL be `0`
- **AND** the other aggregates (`answer_match_mean`, `tool_required_hit_mean`, etc.) SHALL still be populated
