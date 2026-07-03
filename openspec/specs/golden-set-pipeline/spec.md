# golden-set-pipeline Specification

## Purpose

TBD - created by archiving change 'eval-loop-automation'. Update Purpose after archive.

## Requirements

### Requirement: Show profiling drives question-type quotas

The eval tooling SHALL provide a profiling script that measures a show's structural traits (guest coverage ratio, playlist-pattern title count, summary completion ratio, sampled English-character ratio) and writes a per-show profile JSON containing a question-type quota matrix derived from static, human-readable rules. The profile SHALL be manually editable and SHALL include a `recurring_segments` placeholder field for future structured-segment extraction.

#### Scenario: Low guest coverage disables guest questions

- **WHEN** the profiling script runs against a show whose guest coverage ratio is below 0.10
- **THEN** the emitted profile SHALL set the `guest_find` quota to 0 and redistribute its allocation to other core types

##### Example:

Given 壹加壹電台 with 6 of 261 episodes having guests (coverage 0.02), the profile sets `guest_find: 0`; given 這又沒有很屌 with coverage 0.58, `guest_find` receives a non-zero quota.

#### Scenario: Missing summaries suppress summary questions

- **WHEN** the profiled show has a summary completion ratio below the usable threshold
- **THEN** the `summary_overview` quota SHALL be 0 so no unanswerable questions are generated


<!-- @trace
source: eval-loop-automation
updated: 2026-07-03
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/_review_log.jsonl
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/gcp_batch_transcribe/episodes.jsonl
  - skills-lock.json
  - backend/eval/scripts/promote_reviewed.py
  - backend/eval/scripts/show_profile.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/eval/datasets/profiles/this-not-that-cool.json
  - backend/eval/scripts/review_log.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/eval/datasets/yi-jia-yi.json
  - backend/eval/datasets/profiles/yi-jia-yi.json
  - backend/eval/scripts/__init__.py
  - docs/roadmap.md
  - backend/eval/datasets/_pending_review.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
tests:
  - backend/tests/test_show_profile.py
  - backend/tests/test_review_log_promote.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_build_golden_set_v2.py
-->

---
### Requirement: Question generation is anchor-first

The golden-set generation script SHALL select anchor chunks BEFORE generating each question: sample episode(s), sample chunk(s) from those episodes, generate the question from the chunk content, and bind the sampled chunk ids as ground truth. Questions SHALL NOT be generated from show-level impressions with anchors attached afterwards. Multi-turn items SHALL be excluded from automatic generation and marked for handcrafting.

#### Scenario: Anchor exists before question

- **WHEN** a generated staging item is inspected
- **THEN** its ground-truth chunk ids SHALL reference chunks that were sampled prior to question generation, and every chunk SHALL belong to the target show


<!-- @trace
source: eval-loop-automation
updated: 2026-07-03
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/_review_log.jsonl
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/gcp_batch_transcribe/episodes.jsonl
  - skills-lock.json
  - backend/eval/scripts/promote_reviewed.py
  - backend/eval/scripts/show_profile.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/eval/datasets/profiles/this-not-that-cool.json
  - backend/eval/scripts/review_log.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/eval/datasets/yi-jia-yi.json
  - backend/eval/datasets/profiles/yi-jia-yi.json
  - backend/eval/scripts/__init__.py
  - docs/roadmap.md
  - backend/eval/datasets/_pending_review.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
tests:
  - backend/tests/test_show_profile.py
  - backend/tests/test_review_log_promote.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_build_golden_set_v2.py
-->

---
### Requirement: Pre-review grading on staged items

Every staged item SHALL carry a `pre_review` block with four checks: anchor-alignment verification (performed by a model different from the generation model), answerability rubric (must/acceptable tiers), show-id guard (mechanical; failure is the only automatic rejection), and a retrieval-rank signal obtained by querying the live search endpoint. The retrieval signal SHALL only influence the review grade (`light` or `heavy`) and SHALL NOT reject an item.

#### Scenario: Retrieval miss does not reject

- **WHEN** a staged item's anchor chunks do not appear in the top-20 retrieval results for its question
- **THEN** the item SHALL remain in staging with `review_grade: "heavy"` and SHALL NOT be auto-rejected

#### Scenario: Foreign-show anchor is auto-rejected

- **WHEN** any anchor chunk of a staged item belongs to a show other than the target show
- **THEN** the item SHALL be rejected automatically and recorded in the review log


<!-- @trace
source: eval-loop-automation
updated: 2026-07-03
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/_review_log.jsonl
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/gcp_batch_transcribe/episodes.jsonl
  - skills-lock.json
  - backend/eval/scripts/promote_reviewed.py
  - backend/eval/scripts/show_profile.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/eval/datasets/profiles/this-not-that-cool.json
  - backend/eval/scripts/review_log.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/eval/datasets/yi-jia-yi.json
  - backend/eval/datasets/profiles/yi-jia-yi.json
  - backend/eval/scripts/__init__.py
  - docs/roadmap.md
  - backend/eval/datasets/_pending_review.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
tests:
  - backend/tests/test_show_profile.py
  - backend/tests/test_review_log_promote.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_build_golden_set_v2.py
-->

---
### Requirement: Human review verdicts are logged with structured reasons

All staged items SHALL pass human review before entering the main dataset. Each verdict (`approve`, `approve_edited`, `reject`) SHALL be appended to a review log line with a reason drawn from a fixed enumeration (`anchor_mismatch`, `too_shallow`, `keyword_triggered`, `cross_ep_irrelevant`, `ambiguous`, `asr_typo_dependent`, `other`), the show slug, the item id, and the generation round.

#### Scenario: Reject verdict captured

- **WHEN** the reviewer rejects a staged item as too shallow
- **THEN** the review log SHALL gain a line with `verdict: "reject"` and `reason: "too_shallow"` for that item id


<!-- @trace
source: eval-loop-automation
updated: 2026-07-03
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/_review_log.jsonl
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/gcp_batch_transcribe/episodes.jsonl
  - skills-lock.json
  - backend/eval/scripts/promote_reviewed.py
  - backend/eval/scripts/show_profile.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/eval/datasets/profiles/this-not-that-cool.json
  - backend/eval/scripts/review_log.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/eval/datasets/yi-jia-yi.json
  - backend/eval/datasets/profiles/yi-jia-yi.json
  - backend/eval/scripts/__init__.py
  - docs/roadmap.md
  - backend/eval/datasets/_pending_review.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
tests:
  - backend/tests/test_show_profile.py
  - backend/tests/test_review_log_promote.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_build_golden_set_v2.py
-->

---
### Requirement: Reject patterns feed back into generation

The generation script SHALL read the review log before generating and SHALL inject the most frequent reject reasons with concrete rejected examples (capped at 5) into the generation prompt as negative few-shot guidance. Each generation round SHALL report the round's bad-question ratio against the prior round.

#### Scenario: Second round consumes first-round rejects

- **WHEN** a generation round runs after a review log containing rejects exists for the show
- **THEN** the generation prompt SHALL contain at least one rejected example as negative guidance, verifiable via a dry-run flag

<!-- @trace
source: eval-loop-automation
updated: 2026-07-03
code:
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640-answers.md
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.json
  - backend/eval/scripts/build_golden_set.py
  - backend/eval/datasets/_review_log.jsonl
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922-answers.md
  - backend/scripts/gcp_batch_transcribe/episodes.jsonl
  - skills-lock.json
  - backend/eval/scripts/promote_reviewed.py
  - backend/eval/scripts/show_profile.py
  - backend/scripts/bakeoff_out/bakeoff-20260607T115922.md
  - backend/eval/datasets/profiles/this-not-that-cool.json
  - backend/eval/scripts/review_log.py
  - backend/scripts/hyde_ab/results/calibrate-20260606T221058.json
  - backend/eval/datasets/yi-jia-yi.json
  - backend/eval/datasets/profiles/yi-jia-yi.json
  - backend/eval/scripts/__init__.py
  - docs/roadmap.md
  - backend/eval/datasets/_pending_review.json
  - backend/eval/datasets/_chat_rag_schema_v2.json
  - backend/scripts/bakeoff_out/bakeoff-20260607T112640.md
tests:
  - backend/tests/test_show_profile.py
  - backend/tests/test_review_log_promote.py
  - backend/tests/test_golden_set_dataset.py
  - backend/tests/test_build_golden_set_v2.py
-->