## 1. Derive expected_answer_summary and expected_behavior in tiers from answer + human_score

Implements requirement "Mini-set expected fields are derived semi-automatically with an explicit review queue".

- [x] 1.1 (Requirement: Mini-set expected fields are derived semi-automatically with an explicit review queue) Write the deterministic derivation that assigns each of the 40 `_judge_minisset.json` items a tier from (refusal-shaped `answer`?, `human_score`) and computes `expected_behavior` + `expected_answer_summary`. Refusal-shaped detection uses a fixed regex (covering 「資料中沒提到 / 未提及 / 無法回答 / 我不知道 / 找不到 / 沒有足夠資訊」 類). Verify: running it twice yields identical tier assignment and identical review-queue id list.
- [x] 1.2 Auto-fill the trustworthy tiers: non-refusal & `human_score` ≥ 4 → `expected_behavior: "answer"` + summary seeded from `answer`; refusal-shaped & `human_score` ≥ 4 → `expected_behavior: "refuse"` + a short "資料中確無此資訊" summary. Verify: each auto-filled item has a non-sentinel `expected_answer_summary`.
- [x] 1.3 Mark the untrustworthy tiers (refusal & `human_score` ≤ 3; non-refusal & `human_score` ≤ 3) as review-queue items: `expected_answer_summary` = literal `"PENDING AUDIT"`, `expected_behavior` left for human confirmation. Verify: no review-queue item carries a fabricated summary; the script prints the review-queue id list rather than silently applying.

## 2. Human-confirm the review-queue expected_behavior labels (co-draft, not batch)

- [x] 2.1 Walk the ~25 review-queue items one at a time with the user, confirming only the answerable-vs-refuse `expected_behavior` label per item (per feedback_golden_set_co_draft_flow: present each item's question + recorded answer + human_score + proposed label, get confirmation). Do NOT author full expected answers here. Verify: every review-queue item ends with a human-confirmed `expected_behavior` ∈ {answer, refuse, refusal_with_correction}; `expected_answer_summary` stays `"PENDING AUDIT"`.
- [x] 2.2 Confirm all 40 items are now field-complete and the file validates (40 items, every item has both new fields, `expected_behavior` from the allowed set). Verify: a load+assert check passes.

## 3. Shape mini-set items into the production judge payload via an adapter

- [x] 3.1 In the reworked calibration entry point, add an adapter that maps each static mini-set item into the production judge payload: `agent_answer` ← `answer`; a single synthesized `tool_calls` entry `{name, args, result_full}` with `result_full` ← the joined `chunks`; `question`, `expected_answer_summary`, `expected_behavior` ← the item fields. Reuse `build_payload` / `invoke_judge` from `backend/eval/judge_chat_v2.py` unchanged. Verify: the adapter output for a sample item is a valid payload accepted by `build_payload`.

## 4. Reduce four verdicts to one refusal-aware scalar for Spearman

- [x] 4.1 Implement the refusal-aware reduction: when an item's `expected_behavior` is a refusal variant, the scalar is driven by `refusal_appropriateness.verdict` (appropriate → high; mismatch → low); otherwise it is `factual_correctness.score`. Record the exact numeric anchors in the script. Verify: a faithful-refusal item (human_score 5, judge verdict `appropriate`) reduces to a high scalar, not `factual_correctness.score`.

## 5. Point calibration at the production judge (remove the stand-in)

- [x] 5.1 Rework `backend/scripts/llm_judge_calibration.py` so it imports and calls the production judge path (`judge_chat_v2` + `chat_judge_v2.md`), accepts a model override for the sweep, and removes the inline `JUDGE_PROMPT_TMPL` and the hard-coded `JUDGE_MODEL = "gpt-4o"`. Verify: grep confirms no inline judge prompt and no `gpt-4o` literal remain; a single-model run prints a Spearman against `human_score`.

## 6. Re-run the five current judge models and set a reachable threshold on evidence (bake-off table)

Implements requirement "Judge bake-off runs 4 candidates against a hand-scored mini-set".

- [x] 6.1 (Requirement: Judge bake-off runs 4 candidates against a hand-scored mini-set) Run the aligned bake-off over `gpt-5.1`, `gemini-3.5-flash`, `claude-haiku-4-5`, `gpt-5-nano`, `gemini-2.5-flash-lite` against the field-completed mini-set; unreachable models are reported and skipped. Print a table ordered by Spearman desc with per-run `cost_usd` and persist it to a JSON file under `backend/eval/results/`. Verify: the results file exists and lists one row per reachable model, Spearman-sorted.

## 7. Production judge is selected by Spearman threshold and cost

Implements requirement "Production judge is selected by Spearman threshold and cost".

- [x] 7.1 (Requirement: Production judge is selected by Spearman threshold and cost) Set the pass threshold from the aligned-harness result distribution and record it in the result + case study (the historical 0.7 is non-load-bearing). Select the production judge = highest Spearman among threshold passers, lowest cost on ties. If zero models pass, do NOT mutate the config and recommend the C fallback. Verify: the recorded threshold and selected model (or the zero-passer no-mutate decision) appear in the result file.

## 8. Reconcile judge_config drift from the re-run result, not by guessing

- [x] 8.1 Set `PRODUCTION_JUDGE_MODEL` in `backend/eval/judge_config.py` to the evidence-selected model AND update the module's explanatory comment/docstring so the comment and the constant name the same model. Discard the pre-existing inconsistent pair rather than picking one blind. Verify: reading `judge_config.py` shows the constant and the comment naming the identical selected model.

## 9. Record the evidence in a case-study log

- [x] 9.1 Write the R1.3-j harness-alignment evidence log under `docs/case-studies/`: the three-way collision recap, the 0/40 overlap finding, the derivation tiers + review-queue size, the per-model Spearman/cost table, the chosen threshold + selected model, and (if applicable) the C-fallback recommendation. Verify: the log contains the final bake-off numbers and the selection decision.
