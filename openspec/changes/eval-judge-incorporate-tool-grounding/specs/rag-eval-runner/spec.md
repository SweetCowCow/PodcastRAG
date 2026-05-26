## ADDED Requirements

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

## MODIFIED Requirements

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
