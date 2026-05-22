## ADDED Requirements

### Requirement: extended-multi-turn-40 dataset SHALL carry ground_truth_chunk_ids on scored turns

The `backend/eval/datasets/extended-multi-turn-40.json` dataset (version 2 and onward) SHALL include a `ground_truth_chunk_ids` field on every turn whose `design_type` permits chunk-level scoring. A turn is chunk-level-scorable when its expected answer derives from one or more transcript chunks (i.e. the `fact`, `comprehension`, `cross_episode`, `summary`, `negative`, `guest_find`, `topic_find`, `date_find`, `deep_dive`, `show_overview` types on the first turn). The field carries a list of strings in the canonical `ep:<episode_id>@<start_sec>` form already used by `this-not-that-cool.json`. Turns where chunk-level scoring is not meaningful (notably the second and third turns of multi-turn dialogs, which reference prior enumeration episode_ids rather than chunks) SHALL set `ground_truth_chunk_ids` to `null` and the runner SHALL skip Recall@5 for those turns.

After this change, at least 30 of the 40 turns in the dataset SHALL carry a non-null `ground_truth_chunk_ids`; the remaining ≤10 (multi-turn t2/t3) SHALL be `null`. The dataset `version` SHALL be bumped from `1` to `2` and the `notes` field SHALL document the new coverage figure.

#### Scenario: First-turn single-turn item carries ground_truth_chunk_ids

- **GIVEN** a single-turn item with `design_type: cross_episode` and `source: existing:q04-mid-age-opening-view`
- **WHEN** the dataset is loaded after this change is applied
- **THEN** the turn's `ground_truth_chunk_ids` SHALL be a non-empty list copied from `this-not-that-cool.json`'s q04 entry

#### Scenario: Multi-turn ordinal-reference turn keeps ground_truth_chunk_ids null

- **GIVEN** the `mt01` multi-turn item where turn 2 asks "第三集是什麼內容"
- **WHEN** the dataset is loaded after this change is applied
- **THEN** turn 2's `ground_truth_chunk_ids` SHALL be `null`
- **AND** the runner SHALL NOT count this turn in `recall_at_k_mean`

#### Scenario: Dataset version is bumped and notes document the change

- **GIVEN** the updated dataset
- **WHEN** the top-level `version` and `notes` fields are read
- **THEN** `version` SHALL equal 2 (or higher)
- **AND** `notes` SHALL state how many turns carry ground_truth_chunk_ids and how many are null
