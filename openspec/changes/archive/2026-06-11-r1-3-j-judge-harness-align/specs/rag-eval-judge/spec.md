## MODIFIED Requirements

### Requirement: Judge bake-off runs 4 candidates against a hand-scored mini-set

The eval framework SHALL provide a calibration entry point that measures the **production** chat-rag judge against a hand-scored mini-set, so the reported correlation reflects the judge that actually scores chat eval — not a stand-in. The calibration SHALL invoke the production judge path (`backend/eval/judge_chat_v2.py` loading `backend/eval/prompts/chat_judge_v2.md`); it SHALL NOT use an inline self-authored judge prompt and SHALL NOT hard-code a judge model identifier such as `gpt-4o`.

The mini-set SHALL be stored at `backend/eval/datasets/_judge_minisset.json` and SHALL contain 40 items, each with: `question`, `answer` (model-generated), `chunks` (the citation context), `human_score` (integer 1–5), and — added by this change — `expected_answer_summary` (string) and `expected_behavior` (one of `answer` / `refuse` / `refusal_with_correction`). The two added fields are required because the production judge's payload builder reads them to judge whether a question is answerable or should be refused.

Because the mini-set items are static (no live agent run), the calibration SHALL shape each item into the production judge's payload by mapping `agent_answer` from `answer` and synthesizing a single `tool_calls` entry whose `result_full` is the joined `chunks`, then SHALL invoke the production judge over that payload.

The production judge returns four structured verdicts; the calibration SHALL reduce them to a single scalar per item that is rank-correlated against `human_score`. The reduction SHALL be refusal-aware: when `expected_behavior` is a refusal variant the scalar SHALL be driven by `refusal_appropriateness.verdict`, otherwise by `factual_correctness.score`. A faithful refusal that a human rated highly SHALL NOT be reduced to a low scalar.

The bake-off SHALL run these candidate judge models, all via the Zeabur AI Hub OpenAI-compatible endpoint, and print a result table ordered by Spearman descending with a per-run cost estimate:
- `gpt-5.1`
- `gemini-3.5-flash`
- `claude-haiku-4-5`
- `gpt-5-nano`
- `gemini-2.5-flash-lite`

A candidate model that is unreachable on the endpoint at run time SHALL be reported and skipped, not assumed to pass or fail.

#### Scenario: Calibration invokes the production judge, not a stand-in

- **WHEN** the calibration entry point is inspected
- **THEN** it SHALL import and call `backend/eval/judge_chat_v2.py` (production prompt + a model from `judge_config.py` or an explicit sweep override)
- **AND** it SHALL contain no inline judge prompt template
- **AND** it SHALL contain no hard-coded `gpt-4o` judge model

#### Scenario: Mini-set has 40 items each carrying the two new fields

- **WHEN** the mini-set JSON is loaded
- **THEN** the `items[]` length SHALL equal 40
- **AND** every item's `human_score` SHALL be an integer in `{1, 2, 3, 4, 5}`
- **AND** every item SHALL carry a string `expected_answer_summary`
- **AND** every item's `expected_behavior` SHALL be one of `answer`, `refuse`, `refusal_with_correction`

#### Scenario: Refusal-aware scalar keeps faithful refusals high

- **GIVEN** a mini-set item whose `answer` is a faithful refusal, `human_score` 5, and `expected_behavior` `refuse`
- **WHEN** the production judge returns `refusal_appropriateness.verdict: "appropriate"`
- **THEN** the reduced scalar for that item SHALL be high (consistent with the human_score), driven by `refusal_appropriateness`
- **AND** it SHALL NOT be taken from `factual_correctness.score`

#### Scenario: Bake-off writes a comparable result table over the five current models

- **WHEN** the aligned bake-off is executed
- **THEN** it SHALL print one row per reachable candidate with columns `model`, `spearman`, `pass_threshold`, `cost_usd`
- **AND** rows SHALL be ordered by `spearman` descending
- **AND** the result table SHALL be persisted to a JSON file under `backend/eval/results/`

### Requirement: Production judge is selected by Spearman threshold and cost

The eval framework SHALL select the production judge model from the **aligned** bake-off evidence via this rule:
1. The pass threshold SHALL be set from the aligned-harness result distribution and recorded alongside the result; the historical `0.7` value is treated as non-load-bearing because no model ever met it and the aligned harness changes the measured numbers.
2. From bake-off results, retain only candidates meeting the recorded threshold.
3. Among retained candidates, select the one with the highest Spearman; on a tie, select the lowest `cost_usd`.
4. Write the selection into `backend/eval/judge_config.py` as `PRODUCTION_JUDGE_MODEL` (a single string), AND update the module's explanatory comment so the comment and the constant name the SAME model. The pre-existing comment/constant inconsistency SHALL be reconciled from the new evidence, NOT by blindly choosing one of the two prior conflicting values.

If zero candidates meet the threshold the calibration SHALL print a clear failure message and SHALL NOT auto-modify `PRODUCTION_JUDGE_MODEL`; it SHALL record that the per-question manual re-score fallback is the recommended next step.

The `gpt-4o` model SHALL be reserved as a cross-check baseline; it SHALL NOT be in the routine bake-off pool because of its higher cost relative to mini-class candidates.

#### Scenario: Highest-Spearman passer (cheapest on tie) becomes production judge

- **GIVEN** aligned bake-off results where two models meet the recorded threshold with equal Spearman but different cost
- **WHEN** the selection rule runs
- **THEN** `PRODUCTION_JUDGE_MODEL` SHALL be set to the cheaper of the two
- **AND** any candidate below the recorded threshold SHALL NOT be considered

#### Scenario: Config comment and constant agree after selection

- **GIVEN** the selection rule has chosen an evidence-selected model
- **WHEN** `backend/eval/judge_config.py` is read after the change
- **THEN** the `PRODUCTION_JUDGE_MODEL` constant SHALL equal the selected model
- **AND** the module's explanatory comment SHALL name the same selected model
- **AND** the two SHALL NOT disagree as they did before this change

#### Scenario: All candidates fail the threshold

- **GIVEN** every candidate scores below the recorded threshold
- **WHEN** the selection rule runs
- **THEN** the calibration SHALL exit with a clear failure message
- **AND** `judge_config.py`'s existing `PRODUCTION_JUDGE_MODEL` SHALL be unchanged
- **AND** the output SHALL recommend the per-question manual re-score fallback

## ADDED Requirements

### Requirement: Mini-set expected fields are derived semi-automatically with an explicit review queue

The two added mini-set fields (`expected_answer_summary`, `expected_behavior`) SHALL be populated by a deterministic, reproducible derivation keyed on whether the item's `answer` is refusal-shaped and on its `human_score`. The mini-set has zero question-text overlap with any field-bearing golden set (verified 0/40), so the fields SHALL NOT be auto-borrowed from another dataset; they are derived from each item's own recorded `answer` + `human_score`.

The derivation SHALL apply these tiers:
- non-refusal answer with `human_score` ≥ 4 → `expected_behavior: "answer"`, `expected_answer_summary` seeded from the item's `answer`.
- refusal-shaped answer with `human_score` ≥ 4 → `expected_behavior: "refuse"`, `expected_answer_summary` a short note that the source material genuinely lacks the information.
- any item whose recorded `answer` cannot be trusted to seed a correct expected answer — refusal-shaped with `human_score` ≤ 3 (wrongly refused yet answerable) OR non-refusal with `human_score` ≤ 3 (answered wrong) → the item enters a human-review queue: `expected_answer_summary` SHALL be the literal sentinel `"PENDING AUDIT"` (never a fabricated answer) and `expected_behavior` SHALL be set by human confirmation of the answerable-vs-refuse label only.

Refusal-shaped detection SHALL use a fixed pattern over `answer`. The derivation SHALL emit the per-item tier assignment and the review-queue id list; review-queue items SHALL NOT be silently auto-filled. Authoring full ground-truth answers for review-queue items is out of scope for this requirement.

#### Scenario: Derivation is deterministic and surfaces the review queue

- **WHEN** the derivation is run twice over the same mini-set
- **THEN** both runs SHALL assign every item to the same tier
- **AND** both runs SHALL produce the same review-queue id list
- **AND** the review-queue id list SHALL be printed, not silently applied

#### Scenario: Untrustworthy items get a sentinel, never a fabricated answer

- **GIVEN** a mini-set item whose `answer` is a refusal but `human_score` is 1 (the question was in fact answerable)
- **WHEN** the derivation runs
- **THEN** the item SHALL enter the review queue
- **AND** its `expected_answer_summary` SHALL be the literal string `"PENDING AUDIT"`
- **AND** its `expected_behavior` SHALL be set by human confirmation, not auto-assigned from the refusal text

##### Example: tier assignment by (refusal-shaped, human_score)

| answer shape | human_score | expected_behavior | expected_answer_summary |
| ------------ | ----------- | ----------------- | ----------------------- |
| non-refusal | 5 | answer | seeded from `answer` |
| non-refusal | 2 | (human-confirmed) | "PENDING AUDIT" |
| refusal | 5 | refuse | short "資料中確無此資訊" note |
| refusal | 1 | (human-confirmed) | "PENDING AUDIT" |
