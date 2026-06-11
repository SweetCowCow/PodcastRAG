## Problem

The LLM-as-judge is the foundation under every chat-eval score, yet its calibration is broken: the latest calibration run reports Spearman 0.414 against a 0.7 pass threshold. Worse, the number is measured against the **wrong judge entirely**.

Three standards collide, and they are all distinct from what production actually runs:

1. **Wrong target.** `backend/scripts/llm_judge_calibration.py` scores with its own self-contained prompt (`JUDGE_PROMPT_TMPL`, a single "使用者體驗評審" 0–1 overall score) and a hard-coded `JUDGE_MODEL = "gpt-4o"`. Production eval scores with `backend/eval/judge_chat_v2.py` driving `backend/eval/prompts/chat_judge_v2.md` (a multi-dimensional rubric returning four structured verdicts) under `PRODUCTION_JUDGE_MODEL`. The calibration measures neither the production prompt nor the production model.

2. **Opposite refusal standard.** The mini-set's human scores treat a faithful refusal as good (human_score 5), but the calibration prompt explicitly defines refusal as failure (0.0–0.2). The mini-set has 10 refusal-shaped answers spanning human_score 1–5; the high-rated faithful-refusal cluster alone drags the correlation toward 0.4.

3. **Unfeedable fields.** The production judge's `build_payload` reads `expected_answer_summary` and `expected_behavior` to decide whether a question is answerable or should be refused. `backend/eval/datasets/_judge_minisset.json` (40 items) carries neither field, so the production judge cannot judge "should this have been refused" at all.

On top of the three-way collision there is a config drift: `backend/eval/judge_config.py` comments say the production judge is `gpt-5-nano` (Spearman 0.414, ⭐ picked), but the constant is `PRODUCTION_JUDGE_MODEL = "gemini-2.5-flash-lite"` (Spearman 0.209, second-worst in the bake-off). Git history shows both lines were already inconsistent in the same commit (db3f909, 2026-05-07), so neither can be assumed the typo.

## Root Cause

Calibration was wired to a stand-in harness (own prompt + gpt-4o) instead of the production judge, and the mini-set was built before the production judge gained its refusal / expected-answer contract. So the 0.414 number does not measure the production judge's accuracy — it measures a different judge against a mini-set that lacks the fields and refusal convention the production judge depends on. The model-selection drift in `judge_config.py` is a downstream symptom: with no trustworthy calibration signal, the production-model constant and the explanatory comment were edited independently and never reconciled.

## Proposed Solution

Align the calibration harness to the production judge, then re-measure and re-select on evidence — without blindly editing the drifted config constant.

1. **Point calibration at the production judge.** Rework `backend/scripts/llm_judge_calibration.py` (or a replacement co-located with the bake-off) to invoke the production judge path — `backend/eval/judge_chat_v2.py` loading `backend/eval/prompts/chat_judge_v2.md` — instead of its own `JUDGE_PROMPT_TMPL` + hard-coded gpt-4o. This requires an adapter that shapes each static mini-set item (`question` / `answer` / `chunks`) into the production judge's payload (`agent_answer` ← `answer`; a synthesized `tool_calls` entry whose `result_full` ← the joined `chunks`), and a documented rule that reduces the judge's four structured verdicts to a single scalar comparable against `human_score` for Spearman (the scalar SHALL account for refusal cases, not just `factual_correctness.score`, so faithful-refusal items are not scored as failures).

2. **Add the two missing fields to the mini-set, semi-automatically.** Populate `expected_answer_summary` and `expected_behavior` on all 40 items of `_judge_minisset.json` using a deterministic derivation from each item's own `answer` + `human_score` (the mini-set has **zero** question-text overlap with any existing golden set, so auto-borrowing from the golden set is not possible — verified 0/40). The single highest-value correction is labelling `expected_behavior` (answerable vs should-refuse) on all 40, because the answerable-vs-refuse axis is exactly what broke the correlation and is what the production judge's `refusal_appropriateness` verdict scores. The derivation tiers and the resulting human-review queue are specified in Success Criteria; per-question authoring of full expected answers for low-scoring answerable items is explicitly out of scope (that is the C fallback).

3. **Re-run the current judge models and re-select on evidence.** With the aligned harness + the two new fields, re-run the bake-off over the five currently-available judge models — `gpt-5.1`, `gemini-3.5-flash`, `claude-haiku-4-5`, `gpt-5-nano`, `gemini-2.5-flash-lite` — and set the production judge from the measured Spearman + cost. Set a reachable pass threshold based on the new evidence (the historical 0.7 was never met by any model; the aligned harness may itself move the numbers).

4. **Reconcile the config drift on evidence, not guesswork.** After the re-run, set `PRODUCTION_JUDGE_MODEL` and the `judge_config.py` explanatory comment to the same evidence-selected model so the comment and the constant agree. This is a reconciliation driven by the new bake-off result, NOT a blind edit choosing one of the two pre-existing inconsistent values.

## Non-Goals

- **Per-question manual re-scoring of the mini-set into judge perspective (the "C" fallback).** If, after this change's aligned harness + semi-auto fields, the Spearman is still below the newly-set threshold, the follow-up is a one-question-at-a-time human re-score of all 40 items. That is a separate change and is NOT attempted here.
- **Authoring full ground-truth answers for low-scoring answerable mini-set items.** Scope ②'s derivation fills `expected_behavior` for all 40 and seeds `expected_answer_summary` only for the items where the recorded `answer` is trustworthy; it does NOT hand-write correct answers for items the system got wrong.
- **Changing the production judge's prompt, rubric, or verdict schema** (`chat_judge_v2.md` / `judge_chat_v2.py`). This change aligns calibration TO the production judge; it does not modify the judge being measured.
- **Re-running the full chat eval or re-baselining downstream eval reports.** Only the judge calibration + model selection is in scope.

## Success Criteria

- Calibration invokes the production judge: the calibration script imports and calls `backend/eval/judge_chat_v2.py` (production prompt + `PRODUCTION_JUDGE_MODEL` or an explicit model override for the sweep), and contains no self-authored judge prompt and no hard-coded `gpt-4o` judge model.
- `_judge_minisset.json` validates with all 40 items carrying both `expected_answer_summary` and `expected_behavior`, where `expected_behavior` ∈ {`answer`, `refuse`, `refusal_with_correction`}.
- The semi-auto derivation is reproducible and its tiers are recorded:
  - non-refusal answer with `human_score` ≥ 4 → `expected_behavior: "answer"`, `expected_answer_summary` seeded from the item's `answer` (auto; ~12 items).
  - refusal-shaped answer with `human_score` ≥ 4 → `expected_behavior: "refuse"`, `expected_answer_summary` a short "資料中確無此資訊" note (auto; ~3 items).
  - any item where the recorded `answer` cannot be trusted to seed a correct expected answer (refusal-shaped with `human_score` ≤ 3, i.e. wrongly-refused-yet-answerable; and non-refusal with `human_score` ≤ 3) → `expected_behavior` set by human review, `expected_answer_summary` left as an explicit `"PENDING AUDIT"` sentinel rather than a fabricated answer (review queue, ~25 items). The review confirms only the answerable-vs-refuse label; it does NOT author full answers.
- The review queue is surfaced explicitly (count + per-item ids) and is NOT silently auto-filled.
- The aligned bake-off runs all five current judge models and prints a result table ordered by Spearman descending with per-run cost, written to a results file under `backend/eval/results/`.
- `judge_config.py`'s `PRODUCTION_JUDGE_MODEL` constant and its explanatory comment name the SAME model after the re-run, and that model is the evidence-selected one (highest Spearman among threshold passers, lowest cost on ties), with the chosen threshold recorded.
- If zero models reach the newly-set threshold, the change records that result and the C fallback is recommended; the config constant is NOT changed to a sub-threshold model silently.

## Impact

- Affected code:
  - Modified: backend/scripts/llm_judge_calibration.py
  - Modified: backend/eval/datasets/_judge_minisset.json
  - Modified: backend/eval/judge_config.py
  - Modified: backend/eval/scripts/judge_bakeoff.py
  - New: backend/eval/results/ (re-run calibration + bake-off result JSON)
  - New: docs/case-studies/ (R1.3-j judge harness alignment evidence log)
