## ADDED Requirements

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
