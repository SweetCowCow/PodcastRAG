## ADDED Requirements

### Requirement: Recall@K and MRR are computed per query against ground-truth chunks

The eval framework SHALL provide two retrieval metrics implemented in pure Python (numpy):
- **Recall@K** (default K=5): `|relevant ∩ topK| / |relevant|` per query. Items with empty `ground_truth_chunk_ids` (e.g., `negative` type) SHALL be excluded from the per-query average.
- **MRR**: `mean(1/rank_of_first_relevant)` where `rank` is 1-based; items where no relevant chunk appears in the returned list SHALL contribute 0 to the mean.

Both functions SHALL accept the canonical `ep:<episode_id>@<start_time>` format and SHALL match by string equality after `start_time` is rounded to 2 decimals.

#### Scenario: Recall@5 with one of two ground-truth chunks in top-5

- **GIVEN** an item with `ground_truth_chunk_ids = ["ep:a@1.00", "ep:b@2.00"]`
- **WHEN** the runner returns top-5 chunks `["ep:c@0.50", "ep:a@1.00", "ep:d@3.00", "ep:e@4.00", "ep:f@5.00"]`
- **THEN** `recall@5` for this item SHALL be `0.5`

#### Scenario: MRR with first relevant at rank 2

- **GIVEN** an item whose first relevant chunk appears at top-list index 1 (rank 2)
- **WHEN** MRR is computed for a single-item set
- **THEN** the MRR value SHALL be `0.5`

#### Scenario: Negative items excluded from recall mean

- **GIVEN** a dataset containing 4 fact items (all top-5 hit) and 1 negative item (empty ground-truth)
- **WHEN** Recall@5 is averaged
- **THEN** the result SHALL be `1.0` (negative item excluded from denominator)

##### Example: 3-item recall computation

| Item   | ground_truth                   | top5 returned                                | per-item recall |
| ------ | ------------------------------ | -------------------------------------------- | --------------- |
| q1     | `["ep:a@1.00"]`                | `["ep:a@1.00", ...]`                         | 1.0             |
| q2     | `["ep:b@2.00", "ep:c@3.00"]`   | `["ep:x@9.00", "ep:b@2.00", ...]`            | 0.5             |
| q3 neg | `[]`                           | `[...]`                                      | excluded        |

- **GIVEN** the table above
- **WHEN** the runner computes Recall@5
- **THEN** the reported recall SHALL be `0.75`

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
