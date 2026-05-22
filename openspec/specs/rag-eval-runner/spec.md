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


<!-- @trace
source: eval-runner-chat-enum-scoring
updated: 2026-05-16
code:
  - backend/eval/datasets/this-not-that-cool.json.bak-20260515T060258Z
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
