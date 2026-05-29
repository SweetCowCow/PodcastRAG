# rag-eval-judge Specification

## Purpose

TBD - created by archiving change 'r1-eval-framework'. Update Purpose after archive.

## Requirements

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

---
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