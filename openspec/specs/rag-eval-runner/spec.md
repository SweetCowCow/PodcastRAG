# rag-eval-runner Specification

## Purpose

TBD - created by archiving change 'r1-eval-framework'. Update Purpose after archive.

## Requirements

### Requirement: Recall@K and MRR are computed per query against ground-truth chunks

For each item the runner SHALL:

1. Call the public search endpoint (`POST /shows/{id}/search`) and retrieve the top-K chunks.
2. Dispatch the per-item recall calculation on `eval_mode`:

- **`eval_mode: "chunk_id"`** (default when field is absent): the runner SHALL compute Recall@K and Reciprocal Rank against `ground_truth_chunk_ids`. The chunk identifier match SHALL be either exact (`metric_level=chunk`, default 10s window via `--match-window-s`) or episode-level (`metric_level=episode`, any chunk from the same episode counts).
- **`eval_mode: "open_set_lenient"`**: the runner SHALL compute per-item recall as `1.0` if any retrieved chunk identifier matches any entry in `ground_truth_chunk_ids` (after the lenient match window applied for chunk_id mode), otherwise `0.0`. These items SHALL aggregate together with `chunk_id` items in the chunk-based Recall group.
- **`eval_mode: "enumeration"`**: the runner SHALL ignore `ground_truth_chunk_ids` and instead compute `episode_set_recall = |retrieved_episode_set ∩ expected_episode_set| / |expected_episode_set|`. `retrieved_episode_set` SHALL be the UNION of two sources: (a) the unique episode UUIDs across the top-K chunks returned by the search endpoint, AND (b) the unique episode UUIDs from `enumeration_episodes` returned by an additional chat endpoint call (`POST /shows/{id}/query` with `mode: "chat"`). `expected_episode_set` comes from the item's `expected_episode_ids`. Enumeration items SHALL NOT appear in the chunk-based Recall@K mean; they SHALL aggregate into a separate `episode_set_recall_mean`.

This requirement applies to the semantic-mode dataset (`this-not-that-cool.json`, `eval_mode` field-driven). For the chat-rag-mode dataset (`extended-multi-turn-40.json` schema_version 2.0+), the runner SHALL instead invoke the plugin graders defined above (`chunk_recall_grouped`, `count_consistency`, `ordinal_resolution`, `answer_contradict_check`) plus the LLM judge for `factual_correctness` and `refusal_appropriateness`. The chat-rag-mode dataset SHALL NOT use the `eval_mode` dispatch above; its scoring contract is the per-item indicator suite from the v2 schema.

All chunk-matching functions SHALL accept the canonical `ep:<episode_id>@<start_time>` format and SHALL match by string equality after `start_time` is rounded to 2 decimals.

The runner SHALL NOT impose pass/fail thresholds on `episode_set_recall`; it reports the raw fractional value per item and the mean across enumeration items, so trends can be tracked.

The runner SHALL only invoke the chat endpoint for items whose `eval_mode == "enumeration"` (in semantic-mode datasets). For chat-rag-mode datasets, the runner SHALL always invoke the chat endpoint regardless of design type (since every chat-rag item exercises the agent loop).

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

#### Scenario: Non-enumeration items skip the chat endpoint call (semantic-mode dataset)

- **GIVEN** items with `eval_mode: "chunk_id"` and items with `eval_mode: "open_set_lenient"` in a semantic-mode dataset (`this-not-that-cool.json`)
- **WHEN** the runner processes them
- **THEN** the runner SHALL NOT issue any `POST /shows/{id}/query` call for these items
- **AND** their retrieval cost SHALL be identical to runs before this change shipped

#### Scenario: chat-rag-mode dataset uses plugin graders instead of eval_mode dispatch

- **GIVEN** the dataset `extended-multi-turn-40.json` carrying top-level `schema_version: "2.0"`
- **WHEN** the runner processes any item from this dataset
- **THEN** the runner SHALL skip the `eval_mode` dispatch above
- **AND** the runner SHALL invoke every plugin grader under `backend/eval/graders/` exactly once per item
- **AND** the runner SHALL invoke the chat-rag LLM judge exactly once per item to populate `factual_correctness`, `refusal_appropriateness`, and `answer_contradict_check`


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
### Requirement: Faithfulness and Answer Relevancy are scored via DeepEval with a configured judge

The eval framework SHALL use DeepEval's `FaithfulnessMetric` and `AnswerRelevancyMetric` for the two LLM-judge metrics. The judge model SHALL be read from a single configuration file at `backend/eval/judge_config.py` exporting `PRODUCTION_JUDGE_MODEL` (string identifier passed to DeepEval) and `JUDGE_PROVIDER_BASE_URL` (string for Zeabur AI Hub or OpenAI). DeepEval SHALL be configured to call the judge via the OpenAI-compatible client pointing at that base URL.

#### Scenario: Judge config loads from one file

- **WHEN** the runner imports `backend/eval/judge_config.py`
- **THEN** it SHALL find `PRODUCTION_JUDGE_MODEL` as a non-empty string
- **AND** `JUDGE_PROVIDER_BASE_URL` as a valid HTTPS URL

#### Scenario: Faithfulness metric runs against a citation context

- **GIVEN** a query result with `answer="主持人說 Puzzleman 介紹 lo-fi"` and citations whose chunks contain that exact statement
- **WHEN** `FaithfulnessMetric` is run
- **THEN** the metric SHALL produce a score in `[0, 1]`
- **AND** the score SHALL NOT raise — i.e., the judge call succeeds and returns a parseable result

---
### Requirement: eval/run.py orchestrates one full eval run end-to-end

`backend/eval/run.py` SHALL be a CLI entry point accepting at minimum:
- `--dataset <slug-or-path>`: dataset slug (e.g., `this-not-that-cool`) or absolute file path
- `--backend-url <url>`: base URL of a running backend (default `http://localhost:8000`)
- `--auth-token <token>`: session token for the admin user (env var fallback `EVAL_AUTH_TOKEN`)
- `--top-k <int>`: K for Recall@K (default 5)
- `--out <path>`: output JSON path (default `backend/eval/results/{date}-{show_slug}.json`)

For each item in the dataset the runner SHALL `POST /shows/{show_id}/query` with the question, collect `answer` + `citations`, compute Recall@K + MRR + Faithfulness + AnswerRelevancy, and write a single JSON output containing per-item scores AND aggregated metrics (overall + per-show — for v1 this means a single show, but the format SHALL accommodate multi-show runs in the future).

#### Scenario: One full run produces a result file

- **GIVEN** backend is up at localhost:8000 with admin session and dataset `this-not-that-cool` loaded
- **WHEN** `python backend/eval/run.py --dataset this-not-that-cool` is executed
- **THEN** the command SHALL exit with code 0
- **AND** `backend/eval/results/{date}-this-not-that-cool.json` SHALL exist
- **AND** the file SHALL contain top-level keys `dataset`, `run_started_at`, `run_finished_at`, `items` (list of per-item rows), `aggregates`

#### Scenario: Aggregates contain overall and per-show breakdowns

- **WHEN** the result file is read
- **THEN** `aggregates.overall` SHALL contain numeric values for `recall_at_5`, `mrr`, `faithfulness`, `answer_relevancy`
- **AND** `aggregates.per_show[show_slug]` SHALL contain the same four numeric values

---
### Requirement: CI runs eval nightly on main and uploads JSON as an artifact

A GitHub Actions workflow at `.github/workflows/eval.yml` SHALL run on:
- `schedule: cron '0 3 * * *'` (UTC 03:00)
- `workflow_dispatch` (manual)

The workflow SHALL run only on the `main` branch. It SHALL boot the backend (using docker-compose or equivalent CI setup), run `python backend/eval/run.py --dataset this-not-that-cool`, and upload the produced JSON file as a GitHub Actions artifact named `eval-results-{run_id}`. A failed eval (non-zero exit) SHALL NOT mark the workflow run as failure for branch protection purposes — the workflow SHALL continue past metric assertion failures and complete the artifact upload.

#### Scenario: Manual workflow_dispatch produces an artifact

- **GIVEN** the workflow file is on `main`
- **WHEN** an authorized user triggers `workflow_dispatch`
- **THEN** the run SHALL complete with an `eval-results-*` artifact attached
- **AND** the artifact SHALL contain `{date}-this-not-that-cool.json`

#### Scenario: PR commit does not trigger the workflow

- **WHEN** a PR is opened against main
- **THEN** the eval workflow SHALL NOT run for that PR

---
### Requirement: Canary mode (--canary N)

The eval runner SHALL accept a `--canary N` CLI flag where N is a positive integer. When set, the runner SHALL process only the first N items of the dataset (preserving original order) and SHALL exit normally with a complete report covering exactly those N items. Aggregate metrics SHALL be computed over the N items only. The output filename SHALL include a `.canary` suffix to distinguish from full runs (e.g. `eval-this-not-that-cool-20260510T123456Z.canary.json`).

#### Scenario: --canary 3 limits processing

- **GIVEN** a dataset of 48 items
- **WHEN** `python -m backend.eval.runners.run --canary 3 ...` is invoked
- **THEN** exactly 3 items SHALL be processed (the first 3 in dataset order)
- **AND** the output file SHALL contain `aggregate.overall.n == 3`
- **AND** the output filename SHALL match `eval-*.canary.json` and `eval-*.canary.md`

#### Scenario: --canary 0 or negative is rejected

- **WHEN** `python -m backend.eval.runners.run --canary 0 ...` is invoked
- **THEN** the runner SHALL exit with non-zero status
- **AND** print an error message indicating `--canary` must be a positive integer

#### Scenario: --canary not set runs full dataset

- **WHEN** the flag is omitted
- **THEN** all dataset items SHALL be processed (existing behaviour preserved)


<!-- @trace
source: eval-runner-flags-patch
updated: 2026-05-11
code:
  - src/releaseLog.jsx
  - docs/roadmap.md
  - backend/eval/runners/run.py
  - CLAUDE.md
tests:
  - backend/tests/test_eval_runner_flags.py
-->

---
### Requirement: Answer persistence (--persist-answers)

The eval runner SHALL accept a `--persist-answers` flag (boolean, default false). When set, every per-item record in the JSON report SHALL include the following additional fields beyond the existing `recall_at_k` / `reciprocal_rank` / `judge_score` / `latency_ms`:

- `question` (string): the question sent to the backend (already in dataset, copied for convenience)
- `retrieved_chunk_ids` (list of strings): the top-K chunk_ids returned by `/search`
- `retrieved_texts` (list of strings): the chunk texts returned (truncated to 4000 chars each)
- `answer` (string): the LLM-generated answer from `/query` (post-strip if `_strip_inline_citations` enabled)
- `retrieval_context_for_judge` (list of strings): the context passed to the GEval judge

When `--persist-answers` is NOT set, per-item records SHALL only contain the metric fields (existing behaviour, smaller files for production use).

#### Scenario: --persist-answers enables answer dump

- **GIVEN** `--persist-answers` is set
- **WHEN** the runner completes
- **THEN** every item in the JSON `items` array SHALL have non-null `question`, `retrieved_chunk_ids`, `retrieved_texts`, `answer`, `retrieval_context_for_judge` keys

#### Scenario: --persist-answers default off keeps lean output

- **WHEN** the flag is omitted
- **THEN** per-item records SHALL NOT include `answer` / `retrieved_texts` / `retrieval_context_for_judge` keys
- **AND** the JSON file size SHALL be < 50% of the persist-on equivalent for the same dataset


<!-- @trace
source: eval-runner-flags-patch
updated: 2026-05-11
code:
  - src/releaseLog.jsx
  - docs/roadmap.md
  - backend/eval/runners/run.py
  - CLAUDE.md
tests:
  - backend/tests/test_eval_runner_flags.py
-->

---
### Requirement: Checkpointing (--checkpoint-every N + --resume)

The eval runner SHALL accept `--checkpoint-every N` (positive integer, default 0 = disabled) and `--resume <path>` (path to a checkpoint JSON, default None) flags.

When `--checkpoint-every N > 0`, after every N completed items the runner SHALL write `<out-dir>/.checkpoint.json` containing the per-item records processed so far + a metadata block (run config, dataset path, timestamp). On normal completion the checkpoint file SHALL be deleted.

When `--resume <path>` is set, the runner SHALL load the checkpoint, skip items already processed (by item id), continue with remaining items, and produce a final report indistinguishable from a single uninterrupted run (covering all items).

#### Scenario: Checkpoint written every N items

- **GIVEN** `--checkpoint-every 10` and a 48-item dataset
- **WHEN** the runner has processed exactly 30 items
- **THEN** `<out-dir>/.checkpoint.json` SHALL exist and contain 30 per-item records
- **AND** the metadata block SHALL contain `dataset` path and original run config flags

#### Scenario: Checkpoint deleted on success

- **WHEN** the runner completes all items normally
- **THEN** `<out-dir>/.checkpoint.json` SHALL NOT exist after the final report is written

#### Scenario: --resume skips processed items

- **GIVEN** a checkpoint file with 30 of 48 items recorded
- **WHEN** `--resume <path>` is set on a new run with the same dataset
- **THEN** the runner SHALL skip the first 30 (by item id matching) and process only the remaining 18
- **AND** the final report SHALL contain 48 items in original dataset order

#### Scenario: --resume with mismatched dataset rejects

- **GIVEN** a checkpoint recorded against `dataset-A.json`
- **WHEN** `--resume` is invoked but `--dataset dataset-B.json` is provided
- **THEN** the runner SHALL exit with non-zero status
- **AND** print an error message naming both dataset paths

#### Scenario: Existing flags not affected

- **WHEN** none of the new flags are set
- **THEN** the runner behaviour SHALL be identical to v1 (no checkpoint, no answer persistence, full dataset, lean output) — back-compat preserved

<!-- @trace
source: eval-runner-flags-patch
updated: 2026-05-11
code:
  - src/releaseLog.jsx
  - docs/roadmap.md
  - backend/eval/runners/run.py
  - CLAUDE.md
tests:
  - backend/tests/test_eval_runner_flags.py
-->

---
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


<!-- @trace
source: eval-runner-chat-enum-scoring
updated: 2026-05-16
code:
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
-->

---
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

<!-- @trace
source: eval-runner-chat-enum-scoring
updated: 2026-05-16
code:
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
-->

---
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

---
### Requirement: runner SHALL load chat-rag graders via plugin discovery

The chat-rag eval runner (`backend/scripts/run_chat_agent_eval.py`) SHALL discover grader modules under `backend/eval/graders/` at startup. Each grader module SHALL expose a top-level `grade(item: dict, agent_response: dict) -> dict | None` function with the contract:

- Return `None` when the grader does not apply to the given item (e.g., `ordinal_resolution.grade` returns None for non-multi-turn items)
- Return `{"score": float in [0.0, 1.0], "passed": bool, "details": dict}` when applicable
- Raise no exceptions for normal eval flow; if the grader internally fails, return `{"score": None, "passed": False, "details": {"error": str}}` so the runner can record `"error"` without aborting the run

The runner SHALL invoke every available grader on every item; per-grader applicability is the grader's responsibility (via the `None` return).

#### Scenario: runner discovers all graders in the graders directory

- **GIVEN** the `backend/eval/graders/` directory contains four modules: `count_consistency.py`, `answer_contradict_check.py`, `ordinal_resolution.py`, `chunk_recall_grouped.py`
- **WHEN** the runner starts up
- **THEN** the runner SHALL register all four `grade` functions
- **AND** adding a fifth module SHALL be picked up automatically without runner code changes

#### Scenario: grader returns None for inapplicable item

- **GIVEN** a single-turn `deep_dive` item (e.g., b15)
- **WHEN** `ordinal_resolution.grade(item, response)` is called
- **THEN** the grader SHALL return `None`
- **AND** the runner SHALL NOT record any `ordinal_resolution_check` score for this item


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
### Requirement: count_consistency grader SHALL detect LLM number hallucination on enumeration items

The grader at `backend/eval/graders/count_consistency.py` SHALL extract the first integer in `agent_response.answer` that precedes a Chinese measure word (`集` or `個`) OR follows the literal `共` (e.g., `26 集`, `共 27 個`), and SHALL compare that integer to `agent_response.enumeration_total`. The grader SHALL return `passed: True` when the integers match OR when no count pattern is found in the answer (graceful skip when the LLM did not assert a count). The grader SHALL return `passed: False` ONLY when a count pattern is found AND the integer differs from `enumeration_total`. The grader SHALL return `None` when the item lacks `expected_count` (signalling the item type does not require count consistency).

#### Scenario: agent off-by-one count is detected

- **GIVEN** the b11 item with `expected_count: 26`
- **AND** the agent response has `enumeration_total: 26` and answer text `"共發表了 27 集節目"`
- **WHEN** `count_consistency.grade(item, response)` is called
- **THEN** the result SHALL be `{"score": 0.0, "passed": False, "details": {"detected_count": 27, "enumeration_total": 26}}`

#### Scenario: agent answer that omits a count number passes

- **GIVEN** an item with `expected_count: 26`
- **AND** the agent answer is a narrative that does NOT mention any integer with the `集` / `個` measure word or `共` prefix
- **WHEN** the grader runs
- **THEN** the result SHALL be `{"score": 1.0, "passed": True, "details": {"detected_count": null}}`

#### Scenario: grader returns None when item lacks expected_count

- **GIVEN** a deep_dive item without `expected_count`
- **WHEN** the grader is called
- **THEN** it SHALL return `None`


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
### Requirement: ordinal_resolution grader SHALL verify multi-turn ordinal resolves to correct episode

The grader at `backend/eval/graders/ordinal_resolution.py` SHALL apply ONLY to multi-turn items whose current turn carries the boolean flag `ordinal_resolution_check: true` AND a non-empty `carry_from` string. The grader SHALL:

1. Parse the `carry_from` directive (supported form for v2: `"t<N>.enumeration_episodes[<index>] sorted by published_at <DESC|ASC>"`)
2. Read the prior turn's response (via runner-supplied turn context) to obtain `enumeration_episodes`
3. Sort by `published_at` per the directive
4. Pick the episode at the specified index → `expected_episode_id`
5. Compare against the current turn's tool call: scan `tool_calls` for any tool whose args contain an `episode_id` key
6. Return `passed: True` when the agent's `episode_id` argument equals the resolved `expected_episode_id`, else `passed: False`

#### Scenario: mt01 t2 EP55 vs EP131 mismatch is caught

- **GIVEN** the mt01 t2 item with `carry_from: "t1.enumeration_episodes[2] sorted by published_at DESC"` and `ordinal_resolution_check: true`
- **AND** the t1 response's `enumeration_episodes` sorted DESC by `published_at` places EP131 (UUID `c1d87278-...`) at index 2
- **AND** the t2 agent tool call is `get_episode_summary({"episode_id": "86115ef5-..."})` (EP55)
- **WHEN** `ordinal_resolution.grade(item, response, prior_turn_context)` is called
- **THEN** the result SHALL be `{"score": 0.0, "passed": False, "details": {"expected_episode_id": "c1d87278-...", "actual_episode_id": "86115ef5-..."}}`

#### Scenario: correct ordinal resolution scores 1.0

- **GIVEN** the same mt01 t2 item but with an agent that correctly calls `get_episode_summary({"episode_id": "c1d87278-..."})`
- **WHEN** the grader runs
- **THEN** the result SHALL be `{"score": 1.0, "passed": True, ...}`

#### Scenario: single-turn item is inapplicable

- **GIVEN** any item with `is_multi_turn: false`
- **WHEN** `ordinal_resolution.grade(...)` is called
- **THEN** the grader SHALL return `None`


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
### Requirement: chunk_recall_grouped grader SHALL credit GT chunks across must / either / acceptable tiers

The grader at `backend/eval/graders/chunk_recall_grouped.py` SHALL compute chunk-level recall against the three-tier GT structure:

- For `ground_truth_chunk_ids_must`: every chunk in the list MUST be in the retrieved top-K. Recall is `|retrieved ∩ must| / |must|`.
- For `ground_truth_chunk_ids_either`: this list is a single equivalence group; ANY one chunk in the group counted as a hit credits the full group. The grader treats `_either` as a single virtual chunk requirement.
- For `ground_truth_chunk_ids_acceptable`: bonus tier. Hits do not affect the main `recall` score but ARE reported in `details.acceptable_hits` for visibility.

The grader's overall `score` SHALL equal `(must_hits + either_group_hit ? 1 : 0) / (|must| + (|either| > 0 ? 1 : 0))`. Chunk match SHALL use the same canonical `ep:<episode_id>@<start_time:.2f>` format and rounding rules as the existing chunk-id matcher (10-second window via `--match-window-s` when configured).

#### Scenario: must hit + either group hit = score 1.0

- **GIVEN** the b14 item with `ground_truth_chunk_ids_must: ["ep:c1d87278-...@0.00"]` and `ground_truth_chunk_ids_either: ["ep:c1d87278-...@1790.18", "ep:c1d87278-...@1808.78"]`
- **AND** the citations contain `ep:c1d87278-...@0.00` and `ep:c1d87278-...@1808.78` (the second of the either group)
- **WHEN** the grader runs
- **THEN** `score` SHALL equal `1.0` (1 must-hit + 1 either-group-hit) / (1 must + 1 either-group)
- **AND** `details.either_group_hit_chunk` SHALL equal `"ep:c1d87278-...@1808.78"`

#### Scenario: missing must chunk scores partial

- **GIVEN** an item with `ground_truth_chunk_ids_must` of length 2 and `_either` / `_acceptable` both null
- **AND** the citations contain only 1 of the 2 must chunks
- **WHEN** the grader runs
- **THEN** `score` SHALL equal `0.5`

#### Scenario: acceptable hits are bonus-only

- **GIVEN** an item where the must chunk is hit AND an acceptable chunk is also hit
- **WHEN** the grader runs
- **THEN** `score` SHALL equal `1.0` (acceptable does NOT raise score beyond 1.0)
- **AND** `details.acceptable_hits` SHALL equal `1`


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
### Requirement: answer_contradict_check grader SHALL invoke LLM judge for contradiction detection

The grader at `backend/eval/graders/answer_contradict_check.py` SHALL invoke the chat-rag LLM judge (defined in spec `rag-eval-judge`) and read the judge's `answer_contradict_check` field. The grader SHALL apply ONLY when the item carries a non-null `expected_must_contradict_check` string. The grader SHALL share the judge invocation with `factual_correctness` and `refusal_appropriateness` (single judge call yields all three) to avoid triple-charging the LLM budget.

#### Scenario: b14 contradiction is detected

- **GIVEN** the b14 item with `expected_must_contradict_check: "answer 不得出現『推薦振奮歌 / 振奮人心』等敘述"`
- **AND** the agent answer contains the phrase `"推薦振奮人心的歌"`
- **WHEN** the LLM judge is invoked and `answer_contradict_check.grade(item, response)` reads the judge output
- **THEN** the grader result SHALL be `{"score": 0.0, "passed": False, "details": {"judge_rationale": "<judge's explanation>"}}`

#### Scenario: inapplicable when item has no contradict directive

- **GIVEN** the b27 item with no `expected_must_contradict_check`
- **WHEN** the grader is called
- **THEN** it SHALL return `None`


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
### Requirement: runner aggregate report SHALL report each indicator independently without cross-design_type averaging

The runner SHALL produce an aggregate report grouped by `design_type` AND by indicator. The report SHALL NOT compute a single overall mean across mixed design types; instead it SHALL emit per-design-type means for each indicator that applied to that subgroup. The output JSON SHALL follow the shape:

```
{
  "by_design_type": {
    "<design_type>": {
      "n_items": int,
      "indicators": {
        "<indicator_name>": {"n_scored": int, "mean": float, "passed_count": int}
      }
    }
  },
  "overall": {
    "n_items_total": int,
    "by_indicator": {
      "<indicator_name>": {"n_scored": int, "mean": float, "passed_count": int}
    }
  }
}
```

The `overall.by_indicator` block SHALL aggregate the same indicator across all design types where it applied (not cross-indicator). The markdown report SHALL render one table per design type plus one summary table by indicator.

#### Scenario: report separates deep_dive and date_find recall scores

- **GIVEN** an eval run with 3 deep_dive items and 2 date_find items
- **AND** `chunk_recall_grouped` scored only the 3 deep_dive items (date_find items skip chunk-level GT)
- **WHEN** the report is rendered
- **THEN** `by_design_type.deep_dive.indicators.recall_at_k.n_scored` SHALL equal 3
- **AND** `by_design_type.date_find.indicators.recall_at_k` SHALL be absent (grader returned None for date_find)
- **AND** the markdown report SHALL contain separate sections for `deep_dive (n=3)` and `date_find (n=2)`

#### Scenario: per-indicator overall avoids cross-design-type contamination

- **GIVEN** the same run as above
- **WHEN** `overall.by_indicator.recall_at_k` is computed
- **THEN** `n_scored` SHALL equal 3 (not 5) — only items where the indicator applied are counted
- **AND** the report SHALL NOT publish a single "overall pass rate" number averaging across indicators

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
### Requirement: Baseline result files carry provenance metadata

When the chat-rag runner (`backend/eval/run_chat_agent_eval.py`) writes a baseline result JSON to `backend/eval/results/`, the output file SHALL include a top-level `provenance` object with at least the following fields:

- `backend_commit`: the prod backend git commit hash the eval was run against (sourced from a `GET /admin/version` or equivalent endpoint, or recorded via runner CLI flag)
- `dataset_path`: relative path of the dataset file used (e.g. `backend/eval/datasets/extended-multi-turn-40.json`)
- `dataset_schema_version`: the dataset's `schema_version` field (e.g. `2.0`)
- `run_started_at`: UTC ISO-8601 timestamp when the run began
- `run_completed_at`: UTC ISO-8601 timestamp when the run ended (or partial-write timestamp if checkpointed)
- `citation_collector_fix_applied`: boolean — true if the backend commit is at or after `287e73b` (the citation collector fix), recorded as evidence that the baseline is not contaminated by the 2026-05-26 ~ 2026-05-27 `_AGENTIC_SEARCH_TOOLS` whitelist bug

Provenance SHALL be written even on partial runs (when the runner aborts or is checkpointed). The runner SHALL refuse to overwrite an existing baseline file with the same name unless the `--force` flag is passed.

#### Scenario: Successful baseline run records full provenance

- **GIVEN** the runner is invoked against prod backend at commit `336c69d` (post citation fix)
- **AND** the dataset is `extended-multi-turn-40.json` schema_version `2.0`
- **WHEN** the runner completes the 40-turn pass and writes `baseline-post-citation-fix-2026-05-27.json`
- **THEN** the JSON SHALL contain a top-level `provenance` object with `backend_commit = "336c69d"`, `dataset_schema_version = "2.0"`, both timestamps populated, and `citation_collector_fix_applied = true`

#### Scenario: Partial run preserves provenance up to abort point

- **GIVEN** the runner has completed 25 of 40 turns when interrupted
- **WHEN** the checkpoint file is written
- **THEN** the partial JSON SHALL still contain a `provenance` object
- **AND** `run_completed_at` SHALL reflect the partial-write timestamp (not a sentinel like null)

#### Scenario: Refuse to overwrite without --force

- **GIVEN** a baseline file `backend/eval/results/baseline-post-citation-fix-2026-05-27.json` already exists
- **WHEN** the runner is invoked with the same output filename without `--force`
- **THEN** the runner SHALL exit non-zero with a message referencing the existing file and SHALL NOT overwrite it

<!-- @trace
source: eval-baseline-citation-bug-revalidation
updated: 2026-05-27
code:
  - docs/roadmap.md
  - backend/scripts/run_chat_agent_eval_v2.py
  - src/releaseLog.jsx
  - backend/eval/scripts/diff_baselines.py
tests:
  - backend/tests/test_run_chat_agent_eval_v2_provenance.py
-->

---
### Requirement: Chat eval runner SHALL emit OTel-style trace spans to PG and Langfuse

The chat agent eval runner (`run_chat_agent_eval_v2.py` and the underlying `chat_agent` loop) SHALL emit one trace span per LLM call, per tool dispatch, and per named processing stage. Each span SHALL be persisted to the `eval_traces` PostgreSQL table AND streamed to the configured Langfuse host via the Langfuse Python SDK. Span persistence SHALL NOT abort or stall the eval run on transport failure; the writer SHALL log a warning and continue.

#### Scenario: chat eval run produces span tree in PG

- **WHEN** the runner processes a single multi-turn item with 2 turns where each turn uses 2 tool calls and 1 final LLM completion
- **THEN** the `eval_traces` table SHALL contain at least 2 (LLM) + 4 (tool) + N (stage) spans for that `(run_id, item_id)`
- **AND** each span row SHALL include `span_type`, `parent_span_id`, `started_at`, `ended_at`, and the type-specific payload columns (`llm_messages_json`, `tool_args_json`, etc.)

#### Scenario: Langfuse transport failure does not abort eval

- **WHEN** the Langfuse host is unreachable during a chat eval run
- **THEN** the runner SHALL continue processing all dataset items to completion
- **AND** the span_writer SHALL log a warning for each failed transport attempt
- **AND** the PG `eval_traces` writes SHALL succeed independently


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Eval runner SHALL emit a stable `run_id` linking result file to trace spans

The runner SHALL generate a single `run_id` (UUID v4) at the start of each invocation. This `run_id` SHALL appear in the eval result JSON's top-level `meta.run_id` field AND on every `eval_traces` row written during that run. Operators SHALL be able to join a result file to its full span tree via `run_id`.

#### Scenario: result file and trace table share run_id

- **WHEN** the runner writes a result JSON file
- **THEN** the file SHALL contain `meta.run_id: <uuid>`
- **AND** all spans written to `eval_traces` during the same invocation SHALL have `run_id = <same uuid>`


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Runner SHALL support a `--probe` invocation that runs `retrieve_hybrid` with episode filter

The CLI script `backend/eval/scripts/retrieve_probe.py` SHALL accept `--show_id`, `--episode_id`, `--query`, and `--top_k` arguments. It SHALL invoke `app.services.rag.retrieve_hybrid` with `episode_id_filter=[episode_id]` and print a ranked list of chunks with `chunk_id`, `start_time`, `rrf_score`, and a marker indicating whether the chunk is in the dataset's `ground_truth_chunk_ids_*` for any item in the active golden set.

#### Scenario: probe surfaces episode-scoped ranking

- **WHEN** the operator runs `retrieve_probe.py --show_id <S> --episode_id <EP44> --query "伴手禮 現吃好吃 食物" --top_k 20`
- **THEN** stdout SHALL contain a top-20 ranked list with chunk_id, start_time, score
- **AND** any chunk that is a ground-truth chunk for a golden set item in EP44 SHALL be marked with a `[GT:<item_id>]` annotation


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Runner SHALL support a `--fingerprint-diff` invocation comparing search queries across commits

The CLI script `backend/eval/scripts/prompt_fingerprint_diff.py` SHALL accept `--old-commit`, `--new-commit`, and `--dataset` arguments. The script SHALL invoke the chat agent eval pipeline against the named dataset for each commit (assuming the prod backend is already deployed at the target commit OR via a `--backend-old` / `--backend-new` URL pair), then query the `eval_traces` table to extract the `search_query` strings per `(item_id, turn_idx)` for each run, and SHALL print a markdown diff table showing per-item search query changes.

#### Scenario: fingerprint diff captures prompt-induced query drift

- **WHEN** the operator runs `prompt_fingerprint_diff.py` against two commits where the only difference is the chat agent SYSTEM_PROMPT
- **THEN** stdout SHALL contain a markdown table with columns `item_id | turn_idx | old_query | new_query | changed`
- **AND** items whose `search_query` differs SHALL have `changed = true`


<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->

---
### Requirement: Runner aggregate SHALL include DeepEval and entity recall indicators

The chat eval runner SHALL aggregate scores grouped by `design_type` across all dataset items, reporting mean and pass_count per indicator. After this change, the aggregated indicator set SHALL include the existing six grader outputs (`chunk_recall_grouped`, `factual_correctness`, `refusal_appropriateness`, `count_consistency`, `ordinal_resolution`, `answer_contradict_check`, `pronoun_attribution_check`) AND four new grader outputs from the DeepEval integration (`answer_relevancy`, `contextual_precision`, `answer_similarity`, `faithfulness_deepeval`) plus the `context_entity_recall` GEval grader.

#### Scenario: aggregate includes new grader outputs

- **WHEN** the runner completes a full 34-item chat eval and writes the result JSON
- **THEN** the `aggregate.overall.by_indicator` object SHALL contain entries for all eleven indicators listed above
- **AND** each entry SHALL include `n_scored`, `mean`, and `passed_count` keys

<!-- @trace
source: eval-framework-upgrade
updated: 2026-05-30
code:
  - skills-lock.json
-->