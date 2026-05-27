## ADDED Requirements

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
