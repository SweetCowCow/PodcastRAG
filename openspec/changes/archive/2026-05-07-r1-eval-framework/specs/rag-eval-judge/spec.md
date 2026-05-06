## ADDED Requirements

### Requirement: Judge bake-off runs 4 candidates against a hand-scored mini-set

The eval framework SHALL provide `backend/eval/scripts/judge_bakeoff.py` which executes a model bake-off over a hand-scored mini-set of 20 items. The mini-set SHALL be stored at `backend/eval/datasets/_judge_minisset.json` and SHALL contain 20 items each with: `question`, `answer` (model-generated), `chunks` (the citation context), and `human_score` (integer 1–5 reflecting human judgment of faithfulness).

The bake-off SHALL run these 4 candidate judge models, all via the Zeabur AI Hub OpenAI-compatible endpoint:
- `gpt-5-nano`
- `gemini-2.5-flash-lite`
- `gpt-4o-mini`
- `claude-haiku-4-5`

For each candidate the script SHALL: invoke `FaithfulnessMetric` (or equivalent) on each of the 20 mini-set items, collect the judge score (0–1 normalized), then compute Spearman rank correlation against the human scores. The script SHALL print a result table sorted by Spearman descending with per-run cost estimate (input + output token count × 1M-token rates).

#### Scenario: Bake-off writes a comparable result table

- **WHEN** `python backend/eval/scripts/judge_bakeoff.py` is executed
- **THEN** it SHALL print one row per candidate with columns: `model`, `spearman`, `pass_threshold` (true if spearman > 0.7), `cost_usd`
- **AND** rows SHALL be ordered by `spearman` descending

#### Scenario: Mini-set has 20 items

- **WHEN** the mini-set JSON is loaded
- **THEN** the `items[]` length SHALL equal 20
- **AND** every item's `human_score` SHALL be an integer in `{1, 2, 3, 4, 5}`

### Requirement: Production judge is selected by Spearman threshold and cost

The eval framework SHALL select the production judge model via this rule:
1. From bake-off results, retain only candidates with Spearman ≥ 0.7
2. Among retained candidates, select the one with the lowest `cost_usd`
3. Write the selection into `backend/eval/judge_config.py` as `PRODUCTION_JUDGE_MODEL` (a single string)

If zero candidates pass the threshold the script SHALL exit with non-zero code and print a clear failure message; `judge_config.py` SHALL NOT be auto-modified in that case.

The `gpt-4o` model SHALL be reserved as a quarterly cross-check baseline; it SHALL NOT be in the routine bake-off pool because of its 10× higher cost relative to mini-class candidates.

#### Scenario: Lowest-cost passer becomes production judge

- **GIVEN** bake-off results: gpt-5-nano (spearman 0.65), gemini-2.5-flash-lite (spearman 0.78, $0.32), gpt-4o-mini (spearman 0.81, $0.48), claude-haiku-4-5 (spearman 0.84, $3.96)
- **WHEN** the selection rule runs
- **THEN** `PRODUCTION_JUDGE_MODEL` SHALL be set to `gemini-2.5-flash-lite`
- **AND** gpt-5-nano (below threshold) SHALL NOT be considered

#### Scenario: All candidates fail the threshold

- **GIVEN** every candidate scores Spearman < 0.7
- **WHEN** the selection rule runs
- **THEN** the script SHALL exit with non-zero code
- **AND** `judge_config.py`'s existing `PRODUCTION_JUDGE_MODEL` SHALL be unchanged
