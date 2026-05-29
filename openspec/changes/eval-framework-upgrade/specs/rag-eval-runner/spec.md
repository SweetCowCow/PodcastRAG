## ADDED Requirements

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

### Requirement: Eval runner SHALL emit a stable `run_id` linking result file to trace spans

The runner SHALL generate a single `run_id` (UUID v4) at the start of each invocation. This `run_id` SHALL appear in the eval result JSON's top-level `meta.run_id` field AND on every `eval_traces` row written during that run. Operators SHALL be able to join a result file to its full span tree via `run_id`.

#### Scenario: result file and trace table share run_id

- **WHEN** the runner writes a result JSON file
- **THEN** the file SHALL contain `meta.run_id: <uuid>`
- **AND** all spans written to `eval_traces` during the same invocation SHALL have `run_id = <same uuid>`

### Requirement: Runner SHALL support a `--probe` invocation that runs `retrieve_hybrid` with episode filter

The CLI script `backend/eval/scripts/retrieve_probe.py` SHALL accept `--show_id`, `--episode_id`, `--query`, and `--top_k` arguments. It SHALL invoke `app.services.rag.retrieve_hybrid` with `episode_id_filter=[episode_id]` and print a ranked list of chunks with `chunk_id`, `start_time`, `rrf_score`, and a marker indicating whether the chunk is in the dataset's `ground_truth_chunk_ids_*` for any item in the active golden set.

#### Scenario: probe surfaces episode-scoped ranking

- **WHEN** the operator runs `retrieve_probe.py --show_id <S> --episode_id <EP44> --query "伴手禮 現吃好吃 食物" --top_k 20`
- **THEN** stdout SHALL contain a top-20 ranked list with chunk_id, start_time, score
- **AND** any chunk that is a ground-truth chunk for a golden set item in EP44 SHALL be marked with a `[GT:<item_id>]` annotation

### Requirement: Runner SHALL support a `--fingerprint-diff` invocation comparing search queries across commits

The CLI script `backend/eval/scripts/prompt_fingerprint_diff.py` SHALL accept `--old-commit`, `--new-commit`, and `--dataset` arguments. The script SHALL invoke the chat agent eval pipeline against the named dataset for each commit (assuming the prod backend is already deployed at the target commit OR via a `--backend-old` / `--backend-new` URL pair), then query the `eval_traces` table to extract the `search_query` strings per `(item_id, turn_idx)` for each run, and SHALL print a markdown diff table showing per-item search query changes.

#### Scenario: fingerprint diff captures prompt-induced query drift

- **WHEN** the operator runs `prompt_fingerprint_diff.py` against two commits where the only difference is the chat agent SYSTEM_PROMPT
- **THEN** stdout SHALL contain a markdown table with columns `item_id | turn_idx | old_query | new_query | changed`
- **AND** items whose `search_query` differs SHALL have `changed = true`

### Requirement: Runner aggregate SHALL include DeepEval and entity recall indicators

The chat eval runner SHALL aggregate scores grouped by `design_type` across all dataset items, reporting mean and pass_count per indicator. After this change, the aggregated indicator set SHALL include the existing six grader outputs (`chunk_recall_grouped`, `factual_correctness`, `refusal_appropriateness`, `count_consistency`, `ordinal_resolution`, `answer_contradict_check`, `pronoun_attribution_check`) AND four new grader outputs from the DeepEval integration (`answer_relevancy`, `contextual_precision`, `answer_similarity`, `faithfulness_deepeval`) plus the `context_entity_recall` GEval grader.

#### Scenario: aggregate includes new grader outputs

- **WHEN** the runner completes a full 34-item chat eval and writes the result JSON
- **THEN** the `aggregate.overall.by_indicator` object SHALL contain entries for all eleven indicators listed above
- **AND** each entry SHALL include `n_scored`, `mean`, and `passed_count` keys
