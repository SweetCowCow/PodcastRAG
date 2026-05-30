## ADDED Requirements

### Requirement: Chat agent eval runner SHALL generate a run_id and propagate it as an HTTP header

The chat agent eval runner v2 (`backend/scripts/run_chat_agent_eval_v2.py`) SHALL generate a `run_id` string at startup with format `eval-YYYYMMDDTHHMMSSZ-<8-char-hex>` (UTC timestamp + 8 hex chars of randomness). The runner SHALL accept an optional `--run-id <str>` CLI flag that, when provided, overrides the auto-generated value. The runner SHALL include the resolved `run_id` in the result JSON file under the top-level `run_id` field, alongside existing metadata such as `backend_commit` and `timestamps`. For every per-turn HTTP POST to `/shows/{id}/query?debug_trace=true`, the runner SHALL set three request headers: `X-Eval-Run-Id: <run_id>`, `X-Eval-Item-Id: <golden_set_item_id>`, and `X-Eval-Turn-Idx: <turn_index_as_string>`. Multi-turn items SHALL increment `X-Eval-Turn-Idx` per turn starting from `0`; single-turn items SHALL always send `X-Eval-Turn-Idx: 0`.

#### Scenario: runner auto-generates run_id and injects headers

- **WHEN** an operator invokes `run_chat_agent_eval_v2.py` against `_calibration_8.json` without `--run-id`
- **THEN** every outbound request to `/shows/{id}/query?debug_trace=true` carries headers `X-Eval-Run-Id`, `X-Eval-Item-Id`, `X-Eval-Turn-Idx`
- **AND** the resulting JSON file contains a `run_id` field matching the pattern `eval-\d{8}T\d{6}Z-[0-9a-f]{8}`
- **AND** the `run_id` value is identical across all per-turn headers within the same runner invocation

##### Example: header injection across a multi-turn item

- **GIVEN** the runner is invoked at `2026-05-30T15:30:12Z`, generates `run_id = "eval-20260530T153012Z-a1b2c3d4"`, and processes item `mt03` with two turns
- **WHEN** the runner POSTs turn 0 then turn 1 for `mt03`
- **THEN** turn 0 request carries `X-Eval-Run-Id: eval-20260530T153012Z-a1b2c3d4`, `X-Eval-Item-Id: mt03`, `X-Eval-Turn-Idx: 0`
- **AND** turn 1 request carries `X-Eval-Run-Id: eval-20260530T153012Z-a1b2c3d4`, `X-Eval-Item-Id: mt03`, `X-Eval-Turn-Idx: 1`

#### Scenario: operator overrides run_id via CLI flag

- **WHEN** an operator invokes the runner with `--run-id custom-debug-run-1`
- **THEN** every outbound request carries `X-Eval-Run-Id: custom-debug-run-1`
- **AND** the result JSON `run_id` field equals `custom-debug-run-1`

### Requirement: Eval runner SQL RCA demo script SHALL exist and produce three-section output

The codebase SHALL include `backend/eval/scripts/sql_rca_demo.py`, a CLI tool that queries the PG `eval_traces` table for spans emitted under a specific `run_id` and prints three sections of diagnostic output: (1) per-turn span count grouped by `item_id` and `turn_idx`; (2) optional cross-run `search_query` diff when `--compare-run-id <other_run_id>` is supplied; (3) per-turn tool timeline ordered by `started_at` showing `tool_name`, `elapsed_ms`, and span ordering. The script SHALL accept `--run-id <run_id>` as required argument and `--compare-run-id <other_run_id>` as optional argument. The script SHALL print non-empty output for every section when the supplied `run_id` matches spans written by a prior runner invocation that exercised the eval context plumbing.

#### Scenario: demo script prints non-empty output after a calibration run

- **WHEN** an operator runs `run_chat_agent_eval_v2.py` against `_calibration_8.json` followed by `python -m backend.eval.scripts.sql_rca_demo --run-id <that_run_id>`
- **THEN** the demo script prints a per-turn span count table with at least 8 distinct `item_id` values
- **AND** the demo script prints a per-turn tool timeline with at least one row per `(item_id, turn_idx)` pair

### Requirement: Prompt fingerprint diff SHALL support SQL-backed comparison

The `backend/eval/scripts/prompt_fingerprint_diff.py` script SHALL support a new mode `--source=sql` that takes `--run-id-old <r1>` and `--run-id-new <r2>` arguments and reads `search_query` values directly from the PG `eval_traces` table instead of re-invoking the chat agent via HTTP. The SQL-mode output SHALL match the HTTP-inline-mode output format (the existing markdown table with item / turn / tool / old query / new query / changed marker columns). The SQL-mode output for a given pair of `run_id` values SHALL be identical to the HTTP-inline-mode output produced by running both backends side-by-side over the same dataset, for every `(item_id, turn_idx, tool_name, query)` tuple.

#### Scenario: SQL mode reproduces inline-HTTP mode diff for the same runs

- **GIVEN** runner v2 has been invoked twice over `_calibration_8.json`, producing two `run_id` values `eval-A` and `eval-B`, with each turn writing a span containing the agent's `search_query` to `eval_traces`
- **WHEN** an operator runs `prompt_fingerprint_diff.py --source=sql --run-id-old eval-A --run-id-new eval-B --output /tmp/sql.md`
- **AND** an operator also runs the legacy HTTP-inline mode over the same two backend deployments
- **THEN** the per-row entries in `/tmp/sql.md` match the legacy HTTP-inline-mode markdown table for every `(item_id, turn_idx, tool_name)` triple
