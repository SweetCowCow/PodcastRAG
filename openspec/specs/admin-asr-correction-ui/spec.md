# admin-asr-correction-ui Specification

## Purpose

TBD - created by archiving change 'asr-correction-dictionary'. Update Purpose after archive.

## Requirements

### Requirement: Admin tab manages correction rules

The admin panel SHALL provide an ASR correction tab that lists existing rules showing `wrong`, `correct`, `scope`, the bound show, and the enabled state, and SHALL allow creating, editing, enabling or disabling, and deleting rules. The tab SHALL be bilingual (Traditional Chinese and English) and SHALL use the shared TOKEN design system.

#### Scenario: List and create rule

- **WHEN** an admin opens the ASR correction tab
- **THEN** the tab SHALL display existing rules and SHALL provide a form to create a new rule with `wrong`, `correct`, `scope`, a bound show when scope is `show`, and an optional note

#### Scenario: Toggle enabled

- **WHEN** an admin disables a rule
- **THEN** the rule SHALL be marked disabled and SHALL stop being applied


<!-- @trace
source: asr-correction-dictionary
updated: 2026-06-01
code:
  - skills-lock.json
  - docs/roadmap.md
-->

---
### Requirement: Match-count preview before save

Before a rule is saved, the tab SHALL display how many existing transcript segments the rule's `wrong` value currently matches within its scope, so the admin can detect an over-broad rule before applying it.

#### Scenario: Preview shows match count

- **WHEN** an admin enters a `wrong` value and a scope
- **THEN** the tab SHALL show the number of currently matching segments before the rule is saved


<!-- @trace
source: asr-correction-dictionary
updated: 2026-06-01
code:
  - skills-lock.json
  - docs/roadmap.md
-->

---
### Requirement: Trigger backfill with progress feedback

The tab SHALL allow triggering a backfill for a chosen scope and SHALL surface its progress and completion, including affected segments, affected chunks, and failures. The tab SHALL inform the admin that newly added rules require a manual backfill to correct existing transcripts.

#### Scenario: Trigger backfill

- **WHEN** an admin triggers a backfill from the tab
- **THEN** the tab SHALL start the backfill and SHALL display its progress and final counts

#### Scenario: Manual backfill notice

- **WHEN** an admin adds a new rule
- **THEN** the tab SHALL indicate that existing transcripts require a manual backfill to reflect the rule

<!-- @trace
source: asr-correction-dictionary
updated: 2026-06-01
code:
  - skills-lock.json
  - docs/roadmap.md
-->

---
### Requirement: Pending candidate review section

The ASR correction admin tab SHALL present a section listing LLM-detected pending candidates (`source='llm'`, `status='pending'`) for review, showing each candidate's `wrong`, `correct`, and bound show. The `correct` value SHALL be presented in an editable field pre-filled with the detected value, so an admin can adjust it before approving; approving SHALL send the (possibly edited) `correct` to the approve endpoint. The section SHALL also provide a reject control. The section SHALL be bilingual (zh/en) and SHALL use the existing design tokens. After approve or reject, the list SHALL reflect the updated state.

#### Scenario: Candidate list loads with editable correct

- **WHEN** an admin opens the ASR correction tab with pending LLM candidates present
- **THEN** each candidate SHALL show its `correct` in an editable field plus approve and reject controls

#### Scenario: Approve with edited correct

- **WHEN** an admin edits a candidate's `correct` field and approves
- **THEN** the approved rule SHALL use the edited value and the candidate SHALL leave the pending list

#### Scenario: Reject removes candidate from pending list

- **WHEN** an admin rejects a pending candidate
- **THEN** the candidate SHALL no longer appear in the pending list

<!-- @trace
source: asr-correction-ux-and-aihub-json
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
### Requirement: Admin UI triggers detection over a show's existing episodes

The admin ASR correction tab SHALL let an admin trigger homophone detection over a selected show's existing episodes. The UI SHALL first present the dry-run cost estimate (episode count, estimated tokens, estimated USD) and SHALL require explicit confirmation before starting the real run. The tab SHALL remain bilingual (Traditional Chinese and English) and SHALL use the shared TOKEN design system.

#### Scenario: Cost estimate shown before real run

- **WHEN** an admin chooses to detect over a show's existing episodes
- **THEN** the UI SHALL display the dry-run cost estimate and SHALL start the real detection job only after the admin confirms


<!-- @trace
source: asr-homophone-full-backfill
updated: 2026-06-04
code:
  - skills-lock.json
-->

---
### Requirement: Admin UI shows backfill progress, failures, and cancellation

The admin tab SHALL display the progress of a running backfill job (detection or rule application) as a `current`/`total` indicator, SHALL surface the failed chunk ids, and SHALL provide a control to cancel the running job.

#### Scenario: Progress and cancel are visible for a running job

- **WHEN** a backfill job is running and the admin views the ASR correction tab
- **THEN** the UI SHALL show the `current`/`total` progress, any failed chunk ids, and a cancel control that stops the job


<!-- @trace
source: asr-homophone-full-backfill
updated: 2026-06-04
code:
  - skills-lock.json
-->

---
### Requirement: Admin UI offers batch restore and approve-and-apply

The admin tab SHALL provide a batch restore control that reverts the episodes touched by rule application back to their original ASR text. When approving a candidate, the tab SHALL offer an option to also apply the approved rule to existing episodes in the same action.

#### Scenario: Approve with apply-to-existing option

- **WHEN** an admin approves a candidate and selects the apply-to-existing option
- **THEN** the UI SHALL approve the candidate and start a rule-application job for that rule, surfacing the job's progress

#### Scenario: Batch restore control

- **WHEN** an admin triggers batch restore from the tab
- **THEN** the UI SHALL revert the affected episodes to their original ASR text and report the affected counts

<!-- @trace
source: asr-homophone-full-backfill
updated: 2026-06-04
code:
  - skills-lock.json
-->