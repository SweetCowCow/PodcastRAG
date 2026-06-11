# rag-eval-judge Specification

## Purpose

TBD - created by archiving change 'r1-eval-framework'. Update Purpose after archive.

## Requirements

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


<!-- @trace
source: r1-3-j-judge-harness-align
updated: 2026-06-11
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/eval/scripts/judge_bakeoff.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/eval/judge_config.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/scripts/llm_judge_calibration.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/eval/scripts/derive_minisset_expected_fields.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
-->

---
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


<!-- @trace
source: r1-3-j-judge-harness-align
updated: 2026-06-11
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/eval/scripts/judge_bakeoff.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/eval/judge_config.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/scripts/llm_judge_calibration.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/eval/scripts/derive_minisset_expected_fields.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
-->

---
### Requirement: chat-rag LLM judge prompt SHALL incorporate agent tool I/O for grounding

The chat-rag LLM judge SHALL be invoked via a dedicated prompt template at `backend/eval/prompts/chat_judge_v2.md`. The judge input SHALL be a structured JSON payload containing:

- `question`: the user prompt (turn-level for multi-turn)
- `expected_answer_summary`: natural-language expected answer
- `expected_answer_aliases`: optional alias mapping for ASR / synonym handling
- `expected_must_contradict_check`: optional natural-language statement of what the answer MUST NOT contain
- `agent_answer`: the agent's NL answer text
- `tool_calls`: array of objects, each containing `name` (tool name), `args` (argument dict), and `result_full` (the tool's complete result string, capped at `agentic_tool_result_max_chars` which defaults to 8000 characters; the truncation suffix `... (truncated, <N> chars omitted)` SHALL be preserved when present)

The judge SHALL be a single LLM call that returns a strict JSON object with four top-level keys:

- `factual_correctness`: `{"score": float in [0.0, 1.0], "rationale": string}` — semantic comparison of `agent_answer` against `expected_answer_summary` with alias substitution applied before comparison
- `refusal_appropriateness`: `{"verdict": "appropriate" | "should_refuse" | "should_answer", "is_refusal_with_correction": boolean, "rationale": string}` — three-state refusal judgment; `is_refusal_with_correction` is true when the agent refuses the primary question AND volunteers correct context (e.g., b27 declines the championship claim but identifies the guest as a competition judge)
- `answer_contradict_check`: `{"passed": boolean, "rationale": string}` or `null` — only populated when the input includes a non-null `expected_must_contradict_check`; `passed: false` means the answer contains content matching the contradiction pattern
- `pronoun_attribution_check`: `{"verdict": "grounded" | "inferred" | "hallucinated", "rationale": string}` or `null` — only populated when the agent answer mentions at least one specific person name AND the expected answer involves a relationship or interaction between two or more named entities; verdict semantics:
  - `grounded` — at least one `tool_calls.result_full` chunk text directly contains the person name that appears in `agent_answer`
  - `inferred` — chunks contain pronouns (e.g., 「他」「她」「我」) without explicit name, but the surrounding text establishes a clear anchor pointing to the named person in `agent_answer` (e.g., the chunk says "Leo 王 來當暖場 / 他唱了一首歌" — the second-sentence pronoun anchors to Leo 王 in the first sentence)
  - `hallucinated` — chunks contain pronouns whose nearest anchor in the chunk text is a DIFFERENT person than the one the `agent_answer` attributes the action to (e.g., chunk discusses 呂安 and uses 「他」, but `agent_answer` claims Leo 王 performed those actions); OR the chunks contain no anchor at all and the agent_answer attribution is unsupported

The judge prompt SHALL include at least three few-shot examples drawn from the audited items (b14 contradiction case + b15 alias case + b23 pronoun_attribution_check `hallucinated` case) to anchor the rubric. The judge prompt SHALL be cache-friendly: the static prefix (rules + few-shot examples) SHALL be at least 1024 tokens to qualify for Anthropic prompt-cache eligibility.

The judge SHALL be invoked via the same OpenAI-compatible client used by existing graders (Zeabur AI Hub `https://hnd1.aihub.zeabur.ai/v1`). The judge model identifier SHALL be read from `backend/eval/judge_config.py`'s `PRODUCTION_JUDGE_MODEL` constant (set by the existing bake-off selection rule).

#### Scenario: judge returns four structured verdicts in a single call

- **GIVEN** an audited item (e.g., b23) and the corresponding agent response with tool_calls containing `result_full` populated
- **WHEN** the chat-rag judge is invoked with the v2 prompt
- **THEN** the response SHALL be valid JSON containing top-level keys `factual_correctness`, `refusal_appropriateness`, `answer_contradict_check`, and `pronoun_attribution_check`
- **AND** `factual_correctness.score` SHALL be a float between 0.0 and 1.0 inclusive
- **AND** `refusal_appropriateness.verdict` SHALL be one of `"appropriate"`, `"should_refuse"`, `"should_answer"`

#### Scenario: judge sees full tool result text via the tool_calls payload

- **GIVEN** an item with `expected_tool_calls_required: ["search_with_topic_prefilter"]`
- **AND** the agent's response contains the tool call with a non-empty `result_full` of length 6500 characters
- **WHEN** the judge prompt is rendered
- **THEN** the input payload's `tool_calls` array SHALL contain one entry whose `result_full` value is the complete 6500-character tool result
- **AND** when the original result exceeded `agentic_tool_result_max_chars` (default 8000) the value SHALL preserve the literal suffix `... (truncated, <N> chars omitted)` from the agent loop's truncation
- **AND** the field name SHALL be `result_full` (NOT `result_summary`)

#### Scenario: answer_contradict_check is null when the item lacks a contradiction directive

- **GIVEN** an item without `expected_must_contradict_check` set (e.g., b15)
- **WHEN** the judge is invoked
- **THEN** the response's `answer_contradict_check` field SHALL be `null`

#### Scenario: refusal_with_correction bonus is recognized

- **GIVEN** the b27 item with `expected_behavior: "refusal_with_correction"`
- **AND** the agent's answer declines the championship premise AND identifies the guest as a "大嘻哈評審" (competition judge)
- **WHEN** the judge is invoked
- **THEN** `refusal_appropriateness.verdict` SHALL be `"appropriate"`
- **AND** `refusal_appropriateness.is_refusal_with_correction` SHALL be `true`

#### Scenario: pronoun_attribution_check detects hallucinated person attribution

- **GIVEN** the b23 item with `agent_answer` claiming Leo 王 was the audience-of-two protagonist
- **AND** `tool_calls.result_full` contains EP129 chunk text where the audience-of-two story is told via pronouns (「他說觀眾席裡就兩個人 一個是他一個是國蛋」) and the nearest narrative anchor in the chunk is 呂安 (introduced earlier as 茉莉書房 主持人), NOT Leo 王
- **WHEN** the judge is invoked
- **THEN** `pronoun_attribution_check.verdict` SHALL be `"hallucinated"`
- **AND** the rationale SHALL reference the chunk's actual pronoun anchor (e.g., "呂安" or "chunk 內 anchor 非 Leo 王" or equivalent ≤ 80 繁體中文 phrasing)

#### Scenario: pronoun_attribution_check accepts legitimate pronoun inference

- **GIVEN** an item where `agent_answer` mentions a person by name (e.g., "Leo 王 唱了一首歌")
- **AND** `tool_calls.result_full` contains chunks where the person's full name appears in the preceding sentence and the action is described in a following sentence using a pronoun ("Leo 王 來當暖場 / 他唱了一首歌")
- **WHEN** the judge is invoked
- **THEN** `pronoun_attribution_check.verdict` SHALL be `"inferred"`

#### Scenario: pronoun_attribution_check is null when the item does not involve multi-person attribution

- **GIVEN** an item like b04 ("節目大概多久更新一集？") where the expected answer does not involve attributing actions to specific named persons
- **WHEN** the judge is invoked
- **THEN** `pronoun_attribution_check` SHALL be `null`

#### Scenario: judge call retries once on malformed JSON

- **GIVEN** the judge model returns a non-JSON or invalid-shape response
- **WHEN** the runner receives the response
- **THEN** the runner SHALL retry the judge call exactly once with identical input
- **AND** if the retry also fails the runner SHALL record `factual_correctness`, `refusal_appropriateness`, `answer_contradict_check` (when applicable), and `pronoun_attribution_check` (when applicable) as the literal string `"error"` for this item
- **AND** the failure SHALL NOT abort the eval run for remaining items

---
### Requirement: judge prompt template SHALL be version-pinned and externalised

The chat-rag judge prompt SHALL live at `backend/eval/prompts/chat_judge_v2.md` as a markdown file outside the Python source tree. The runner SHALL load the prompt text at startup and SHALL pin the prompt content's SHA-256 hash to each eval run report so prompt changes are auditable in baseline diffs.

#### Scenario: prompt hash appears in eval report

- **GIVEN** a completed eval run
- **WHEN** the markdown report at `backend/eval/results/<run-id>/report.md` is read
- **THEN** the report SHALL contain a line of the form `judge_prompt_sha256: <64-hex-chars>`
- **AND** the hash SHALL match the SHA-256 of the on-disk `chat_judge_v2.md` content at run time

<!-- @trace
source: eval-judge-incorporate-tool-grounding
updated: 2026-05-26
code:
  - backend/eval/prompts/chat_judge_v2.md
  - backend/eval/migrations/audit_overlay_2026_05_26.py
  - backend/eval/runner_v2_aggregate.py
  - backend/scripts/run_chat_agent_eval_v2.py
  - backend/eval/graders/answer_contradict_check.py
  - backend/eval/graders/ordinal_resolution.py
  - backend/eval/graders/chunk_recall_grouped.py
  - backend/eval/graders/count_consistency.py
  - backend/eval/graders/loader.py
  - backend/eval/judge_chat_v2.py
  - docs/eval-strategy.md
  - backend/eval/datasets/extended-multi-turn-40.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/eval/migrations/v1_to_v2_schema.py
  - backend/eval/graders/__init__.py
  - backend/eval/migrations/__init__.py
tests:
  - backend/tests/test_judge_chat_v2.py
  - backend/tests/test_grader_ordinal_resolution.py
  - backend/tests/test_runner_aggregate_v2.py
  - backend/tests/test_grader_chunk_recall_grouped.py
  - backend/tests/test_v1_to_v2_migration.py
  - backend/tests/test_grader_count_consistency.py
  - backend/tests/test_runner_plugin_discovery.py
  - backend/tests/test_grader_contradict.py
-->

---
### Requirement: Judge pipeline SHALL integrate four DeepEval built-in metrics for chat eval

The chat eval judge layer SHALL invoke four DeepEval metric classes (`AnswerRelevancyMetric`, `ContextualPrecisionMetric`, `ContextualRecallMetric`, `FaithfulnessMetric`) for every item, producing a numeric score in `[0, 1]` per metric per item. The DeepEval LLM client SHALL be configured to use the existing `OPENAI_API_KEY` environment variable (the AI Hub key) so no additional secret management is required.

#### Scenario: DeepEval metrics run during chat eval

- **WHEN** the runner processes any dataset item with a non-null `expected_answer_summary` and a non-empty retrieved chunk set
- **THEN** the item's `indicators` object SHALL contain `answer_relevancy`, `contextual_precision`, `contextual_recall`, and `faithfulness_deepeval` entries
- **AND** each entry SHALL include a numeric `score`, a boolean `passed`, and a `details` object with the DeepEval rubric reason

#### Scenario: DeepEval LLM call failure is non-fatal

- **WHEN** the DeepEval client returns an error during metric computation for an item
- **THEN** that indicator's entry for that item SHALL be `{score: null, passed: false, details: {error: <reason>}}`
- **AND** the runner SHALL continue processing remaining items


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Judge SHALL provide an `answer_similarity_geval` grader via DeepEval GEval

The judge pipeline SHALL include an `answer_similarity_geval` grader implemented as a DeepEval `GEval` custom rubric (DeepEval has no built-in `AnswerSimilarityMetric` class as of 2026-05-29 — verified by import). The rubric SHALL ask the judge LLM to compare `actual_output` (agent's answer) against `expected_output` (item's `expected_answer_summary`) on three axes: content coverage, factual consistency, and absence of unsupported additions. The score SHALL be in `[0, 1]`.

#### Scenario: answer similarity reflects semantic match to GT answer

- **WHEN** the agent's answer covers all key points of the expected answer summary with no contradictions and no fabricated additions
- **THEN** `answer_similarity_geval.score` SHALL be ≥ `0.8`
- **AND** `answer_similarity_geval.details.reason` SHALL articulate which axes passed


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Judge SHALL provide a custom `context_entity_recall` grader via DeepEval GEval

The judge pipeline SHALL include a `context_entity_recall` grader implemented as a DeepEval `GEval` custom rubric. The rubric SHALL ask the judge LLM to identify entities (people, episode titles, song / album / book titles, organisations) present in the ground-truth answer summary AND check whether the retrieved chunks collectively contain those entities. The score SHALL be `entities_found / entities_total` rounded to 2 decimals.

#### Scenario: entity recall reflects entity coverage in retrieved chunks

- **WHEN** the ground-truth answer summary mentions 3 distinct entities and the retrieved chunks collectively cover 2 of them
- **THEN** `context_entity_recall.score` SHALL be `0.67`
- **AND** `context_entity_recall.details.entities` SHALL list each entity with a `found: bool` flag


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Existing self-written graders SHALL preserve byte-equivalent behavior after this change

The existing six self-written graders — `chunk_recall_grouped`, `count_consistency`, `ordinal_resolution`, `answer_contradict_check`, `refusal_appropriateness`, `pronoun_attribution_check` — SHALL continue running with identical behavior to their pre-change implementation. After this change, their output schema, scoring logic, and grader plugin registration SHALL be byte-equivalent to the baseline.

#### Scenario: re-running the previous baseline produces identical self-written grader scores

- **WHEN** the runner is invoked against the same dataset and prod backend commit used for `baseline-post-judge-v2-2026-05-27.json`
- **THEN** the six self-written indicator scores per item SHALL match the baseline file within floating-point tolerance
- **AND** any divergence SHALL be treated as a regression to be investigated, not as a feature change

<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
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

<!-- @trace
source: r1-3-j-judge-harness-align
updated: 2026-06-11
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/eval/scripts/judge_bakeoff.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/eval/judge_config.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/scripts/llm_judge_calibration.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - skills-lock.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
  - backend/eval/scripts/derive_minisset_expected_fields.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
-->