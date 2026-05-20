## ADDED Requirements

### Requirement: Bake-off uses a fixed 30-question golden set

A framework bake-off SHALL execute the same 30-question golden set against every candidate framework, controlling all variables except the framework itself (same LLM provider, same tool stubs, same metric runner, same scoring rubric).

The golden set SHALL be composed of:
- 26 single-turn questions selected from the existing `backend/eval/datasets/` corpus to cover at least 7 question types (guest lookup, topic lookup, date/episode-ref lookup, single-episode deep-dive, cross-episode comparison, summary, show overview)
- 4 multi-turn questions explicitly designed to exercise multi-turn memory carry (enumeration carry and focused-episode pin)

Each golden set entry SHALL include an `expected_tool_calls` field (list of tool names) so the metric runner can compute tool selection accuracy.

#### Scenario: All candidate frameworks run identical question set

- **GIVEN** a bake-off with candidate frameworks A, B, E
- **WHEN** the metric runner executes the bake-off
- **THEN** all three frameworks SHALL receive the exact same 30 questions in the exact same order
- **AND** all three SHALL use the same fixed LLM provider and model

#### Scenario: Golden set includes 4 multi-turn questions

- **WHEN** the golden set is loaded
- **THEN** at least 4 entries SHALL have `turn_index > 1` linked by a shared `conversation_id`
- **AND** at least one multi-turn pair SHALL test enumeration carry (resolving an ordinal reference like "第三集" to a prior enumeration result)
- **AND** at least one multi-turn pair SHALL test focused-episode pin (resolving a pronoun like "他" to a previously focused episode's main guest)

---

### Requirement: Metric runner produces five quantitative metrics

The bake-off metric runner SHALL compute and report the following five quantitative metrics per framework per run:

1. **Tool selection accuracy** — set-based precision/recall of the actual tool calls the framework made vs the `expected_tool_calls` for each question (order-insensitive)
2. **Answer correctness** — average of `faithfulness` and `answer_match` scores from the existing `backend/eval/runners/` metric implementations
3. **Average latency per turn** — wall-clock milliseconds from user message in to final answer out, including all intermediate tool calls
4. **Average cost per turn** — USD computed from the LLM provider's `usage` token counts × the hardcoded `MODEL_PRICING` table; tool-stub execution is not counted
5. **Multi-turn pass rate** — fraction of multi-turn target turns (Q2 and Q4 of the 4 multi-turn questions) that pass answer correctness; the prerequisite turns (Q1, Q3) are setup-only and do not count toward the score

#### Scenario: Metric runner outputs all five metrics

- **WHEN** the metric runner finishes a 30-question run for one framework
- **THEN** the output JSON SHALL contain all five named metrics with numeric values
- **AND** the output JSON SHALL include per-question records with raw tool-call lists, latency ms, cost USD, and pass/fail flags so any metric can be recomputed from the record without re-running the LLM

#### Scenario: Cost calculation is reproducible from token counts

- **GIVEN** a per-question record with `input_tokens`, `output_tokens`, and `model_id`
- **WHEN** the cost is recomputed using the `MODEL_PRICING` table
- **THEN** the recomputed value SHALL match the recorded `cost_usd` to within 1e-6 USD

---

### Requirement: Bake-off captures qualitative debug-experience score

The bake-off SHALL collect a qualitative debug-experience score (1-5 scale) for each candidate framework covering three sub-dimensions:

- Trace readability (can a reader follow the tool call sequence, parameters, and results from the framework's default trace output?)
- Stack trace clarity (when a tool raises an exception, does the framework propagate a useful stack trace, or swallow / mangle it?)
- Error message readability (when schema validation fails, a tool is not found, or the LLM emits malformed tool-call JSON, how user-friendly is the framework's error message?)

The qualitative score SHALL be collected through **two parallel channels** and then averaged:

1. **Agent-generated trace appendix** — during the 30-question run, the framework adapter SHALL automatically collect at least one sample trace per question, one deliberately-triggered tool exception, and one deliberately-triggered schema-invalid case, and write them to a section in the bake-off case study document for the human reviewer to score against
2. **Human reviewer hands-on session** — the human reviewer SHALL re-run at least 3 randomly-selected questions in a local REPL for each framework and score the live experience

The final qualitative score per framework SHALL equal `(human_score + appendix_score) / 2`.

#### Scenario: Debug appendix is written automatically during the run

- **WHEN** a framework adapter finishes its 30-question run
- **THEN** the case study document SHALL contain a "Debug 體驗附錄 / <framework name>" section
- **AND** that section SHALL contain at least one sample trace, one exception trace, and one schema-invalid example

#### Scenario: Final qualitative score is the average of two channels

- **GIVEN** human reviewer score = H and appendix score = A for one framework
- **WHEN** the final qualitative score is computed
- **THEN** the value SHALL equal `(H + A) / 2`
- **AND** if the absolute difference `|H - A|` exceeds 2 points, the case study SHALL include an explicit discussion section explaining the divergence

---

### Requirement: Bake-off output is captured in a decision document

The bake-off SHALL produce three written artefacts before being considered complete:

- A metrics comparison table covering all candidate frameworks × all six metrics (5 quantitative + 1 qualitative), with a per-metric winner annotation
- A decision section written into the consuming change's `design.md` stating which framework was selected, why, and what trade-offs the losing candidates carry
- A case study document under `docs/case-studies/` recording the bake-off context, per-framework qualitative impressions, the human reviewer's scoring process, and the final decision

The decision SHALL be evidence-based: it MUST cite specific metric values from the comparison table, not subjective "feels better" judgements.

#### Scenario: Decision section cites specific metric values

- **WHEN** the decision section in the consuming change's design.md is written
- **THEN** it SHALL reference at least three specific metric values from the comparison table
- **AND** for each losing framework, it SHALL state at least one concrete trade-off (e.g., "30% slower latency", "LOC budget exceeded", "qualitative debug score 2.5 vs winner 4.0")

#### Scenario: Case study covers all required sections

- **WHEN** the case study document is finalised
- **THEN** it SHALL contain the bake-off context, per-framework 5-10 line qualitative impressions, the human reviewer scoring process, the metrics comparison table, and the final decision summary
- **AND** it SHALL contain the debug appendix sections required by the qualitative-score requirement above

---

### Requirement: Thin prototypes are constrained to 250 lines of code

Each framework prototype in a bake-off SHALL be implemented in under 250 lines of code, measured by the agent loop file plus framework-specific glue code, **excluding** shared infrastructure (tool stubs, golden set loader, metric runner, cost/latency tracker).

This constraint SHALL be enforced to keep the bake-off focused on the framework's intrinsic ergonomics rather than on how polished a wrapper one author can write around it. Exceeding the LOC budget SHALL itself be treated as a negative bake-off signal indicating framework-need mismatch.

#### Scenario: Prototype LOC is measured and reported

- **WHEN** a framework prototype is checked in
- **THEN** the comparison table SHALL include a LOC column for that framework
- **AND** if any framework exceeds 250 LOC, the decision document SHALL discuss whether the overage indicates a poor framework fit or merely a verbose prototype

---

### Requirement: Bake-off methodology is reusable across future bake-offs

This methodology spec SHALL be written generically enough that future bake-offs (e.g., reranker bake-off, chunking strategy bake-off, judge-model bake-off) can reuse the same structure by substituting:

- The candidate list
- The golden set
- The metric set (some metrics may be domain-specific)
- The prototype LOC budget (may vary by domain)

The methodology SHALL prescribe the *shape* of a bake-off (controlled variables, twin qualitative channels, evidence-based decision doc, case study artefact) rather than locking in domain-specific tools.

#### Scenario: Future bake-off reuses the methodology shape

- **GIVEN** a future bake-off for a different domain (e.g., reranker selection)
- **WHEN** the proposer drafts its change
- **THEN** the proposer SHALL be able to cite this methodology spec and only need to specify the candidate list, golden set, metrics, and LOC budget, without re-deriving the bake-off shape
