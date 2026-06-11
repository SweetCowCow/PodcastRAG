## Context

The chat-eval LLM-as-judge is calibrated by `backend/scripts/llm_judge_calibration.py`, which today scores a 40-item hand-rated mini-set (`backend/eval/datasets/_judge_minisset.json`) with its own prompt and a hard-coded `gpt-4o`. Production eval scores with a different harness entirely: `backend/eval/judge_chat_v2.py` loads `backend/eval/prompts/chat_judge_v2.md`, builds a structured payload via `build_payload`, and returns four verdicts (`factual_correctness`, `refusal_appropriateness`, `answer_contradict_check`, `pronoun_attribution_check`) under `PRODUCTION_JUDGE_MODEL` from `backend/eval/judge_config.py`. The bake-off lives at `backend/eval/scripts/judge_bakeoff.py`.

Three constraints frame the work:
- The production judge consumes `agent_answer` + `tool_calls[].result_full` + `expected_answer_summary` + `expected_behavior`. The mini-set is static (`question` / `answer` / `chunks` / `human_score`) and carries none of the expected-* fields.
- The mini-set has **zero** question-text overlap with any field-bearing golden set (`extended-multi-turn-40.json`, `_calibration_8.json`) — verified 0/40, exact and substring. Auto-borrowing the two fields is impossible.
- The existing `rag-eval-judge` spec encodes the OLD harness assumptions (20 items, `FaithfulnessMetric`, a 0.7 threshold no model ever met). The constant/comment drift in `judge_config.py` (comment says gpt-5-nano picked, constant is gemini-2.5-flash-lite) has existed since commit db3f909 (2026-05-07) and cannot be assumed a one-line typo.

## Goals / Non-Goals

**Goals:**
- Make calibration measure the production judge (production prompt + production-class model), so the Spearman number reflects the judge actually scoring chat eval.
- Give the mini-set the two fields the production judge needs, semi-automatically, with a small explicit human-review queue rather than fabricated answers.
- Re-select the production judge on fresh evidence and reconcile the config drift to a single coherent value.

**Non-Goals:**
- Per-question manual re-scoring of the mini-set into judge perspective (the "C" fallback — only triggered if this change's aligned run still underperforms).
- Hand-authoring correct answers for items the system got wrong.
- Modifying the production judge prompt / rubric / verdict schema.
- Re-running the full chat eval or re-baselining downstream reports.

## Decisions

### Shape mini-set items into the production judge payload via an adapter

The production judge's `build_payload` expects an `agent_response` dict with `answer` and `tool_calls[].result_full`. Mini-set items are static. The adapter maps each item as: `agent_answer` ← `item["answer"]`; `tool_calls` ← a single synthesized entry `{name: "search", args: {}, result_full: "\n\n".join(item["chunks"])}`; `question` ← `item["question"]`; `expected_answer_summary` / `expected_behavior` ← the item's new fields. This reuses `build_payload` and `invoke_judge` unchanged rather than re-implementing the call.

Alternative considered: call the judge model directly with `chat_judge_v2.md` inlined. Rejected — it would re-introduce a second copy of the judge invocation that drifts from production, which is the exact bug being fixed.

### Reduce four verdicts to one refusal-aware scalar for Spearman

`human_score` is a single 1–5 rating; the production judge returns four verdicts. The calibration needs one scalar per item to rank-correlate. Rule: when `expected_behavior` is a refusal variant (`refuse` / `refusal_with_correction`), the scalar is driven by `refusal_appropriateness.verdict` (`appropriate` → high, `should_answer`/`should_refuse` mismatch → low); otherwise the scalar is `factual_correctness.score`. This is the crux fix — a faithful refusal (human_score 5) must map to a high scalar, which a `factual_correctness`-only reduction cannot do. The exact numeric mapping is recorded in the calibration script and the case-study log.

Alternative considered: average all four verdicts into one number. Rejected — `pronoun_attribution_check` and `answer_contradict_check` are null on most items and would inject noise; the human raters were rating faithfulness/refusal, not pronoun grounding.

### Derive expected_answer_summary and expected_behavior in tiers from answer + human_score

Deterministic, reproducible derivation keyed on (refusal-shaped answer?, human_score):
- non-refusal & human_score ≥ 4 → `answer` + summary seeded from `answer` (auto; ~12).
- refusal-shaped & human_score ≥ 4 → `refuse` + summary = short "資料中確無此資訊" note (auto; ~3).
- refusal-shaped & human_score ≤ 3 (wrongly refused yet answerable) AND non-refusal & human_score ≤ 3 (system answered wrong) → `expected_behavior` set by human review; `expected_answer_summary` = literal `"PENDING AUDIT"` sentinel, never a fabricated answer (review queue, ~25).

Refusal-shaped detection uses a fixed regex over `answer` (覆蓋 「資料中沒提到 / 未提及 / 無法回答 / 我不知道 / 找不到 / 沒有足夠資訊」 類). The derivation script emits the per-item tier assignment and the review-queue id list so nothing is silently auto-filled. The single non-negotiable output is a correct `expected_behavior` on all 40, because the answerable-vs-refuse axis is what broke the correlation.

Alternative considered: borrow the two fields from the golden set. Rejected — 0/40 question overlap makes it a no-op.

### Re-run the five current judge models and set a reachable threshold on evidence

The aligned bake-off runs `gpt-5.1`, `gemini-3.5-flash`, `claude-haiku-4-5`, `gpt-5-nano`, `gemini-2.5-flash-lite` over the field-completed mini-set and prints a table ordered by Spearman desc with per-run cost. The 0.7 threshold is treated as historical, not load-bearing — the aligned harness changes the measured numbers, so the new threshold is set from the observed distribution (and recorded). Selection rule on threshold passers: highest Spearman, lowest cost on ties.

### Reconcile judge_config drift from the re-run result, not by guessing

After the re-run, `PRODUCTION_JUDGE_MODEL` and the explanatory comment in `judge_config.py` are both set to the evidence-selected model so they agree. The pre-existing inconsistent pair (comment gpt-5-nano / constant gemini-2.5-flash-lite) is discarded rather than one side being picked blind. If zero models reach the threshold, the config constant is left unchanged and the C fallback is recommended in the case-study log.

## Implementation Contract

**Behavior / interface:**
- `backend/scripts/llm_judge_calibration.py` (reworked) imports `backend.eval.judge_chat_v2` (`build_payload`, `invoke_judge`) and `backend.eval.judge_config`; it contains no inline judge prompt and no hard-coded `gpt-4o`. It accepts a model override so the same script drives the multi-model sweep. Output: a results JSON under `backend/eval/results/` plus a printed Spearman/cost table.
- `backend/eval/datasets/_judge_minisset.json`: every one of the 40 items gains `expected_answer_summary` (string) and `expected_behavior` (one of `answer` / `refuse` / `refusal_with_correction`). Items in the review queue carry `expected_answer_summary: "PENDING AUDIT"` until human-confirmed.
- `backend/eval/judge_config.py`: `PRODUCTION_JUDGE_MODEL` and the module docstring/comment name the same evidence-selected model; the chosen Spearman threshold is recorded.

**Failure modes:**
- Judge call malformed/erroring on an item → reuse `judge_chat_v2`'s existing 1-retry-then-error-envelope; that item is dropped from the correlation, not fatal.
- Zero models reach threshold → script reports it, does NOT mutate `PRODUCTION_JUDGE_MODEL`, recommends C.
- A mini-set item whose tier cannot be auto-resolved → it lands in the review queue with `"PENDING AUDIT"`, surfaced in the script output; it is never given a fabricated summary.

**Acceptance criteria:**
- Re-running the aligned calibration reproduces the same per-item tier assignment and review-queue id list (deterministic).
- The mini-set validates with all 40 items field-complete; refusal items carry a refusal `expected_behavior`.
- The bake-off table lists all five models, Spearman desc, with cost; written to results.
- `judge_config.py` comment and constant agree and match the selected model.

**Scope boundaries:** in scope = calibration harness alignment, mini-set two-field population (semi-auto + small review), model re-run/selection, config reconciliation. Out of scope = production judge prompt/schema, full per-question re-scoring (C), downstream eval re-baseline.

## Risks / Trade-offs

- [Review queue larger than "a few" — ~25/40 items need human confirmation because the mini-set is low-score-heavy (23 items ≤3)] → Mitigation: the review in B only confirms the binary answerable-vs-refuse `expected_behavior` label (cheap), not full answer authoring; `expected_answer_summary` stays `"PENDING AUDIT"` for those, deferring expensive work to C only if the aligned Spearman still underperforms.
- [Verdict→scalar mapping is a judgement call that could itself bias the correlation] → Mitigation: the mapping is recorded explicitly in the script + case study; if it proves brittle, it is a single localized knob to revisit, not spread across the harness.
- [Aligned harness may STILL not reach a high Spearman] → Mitigation: that is an acceptable, informative outcome — it proves the harness, not the metric design, was the residual issue and cleanly motivates C. The change records the result rather than forcing a pass.
- [Synthesized single `tool_calls` entry differs from the multi-call shape production agents produce] → Mitigation: the mini-set was always single-context (chunks blob); the adapter faithfully represents what the human rater saw, which is the correct calibration target.

## Migration Plan

No runtime/prod deployment — this is eval-harness + dataset tooling. Rollback = revert the change's commits; `_judge_minisset.json` and `judge_config.py` return to prior content. The production judge path (`judge_chat_v2.py` / `chat_judge_v2.md`) is untouched, so chat eval behavior is unaffected during and after the change.

## Open Questions

- Exact numeric values of the refusal-aware scalar mapping (high/low anchors) — to be fixed in implementation and recorded; not blocking the design.
- Whether `gemini-3.5-flash` / `gpt-5.1` are reachable on the current AI Hub endpoint at run time — to be confirmed at re-run; unreachable models are reported and skipped, not assumed.
