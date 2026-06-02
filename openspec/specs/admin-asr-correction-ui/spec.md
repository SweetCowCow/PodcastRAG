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

The ASR correction admin tab SHALL present a section listing LLM-detected pending candidates (`source='llm'`, `status='pending'`) for review, showing each candidate's `wrong`, `correct`, and bound show, with controls to approve or reject each candidate. The section SHALL be bilingual (zh/en) and SHALL use the existing design tokens. After approve or reject, the list SHALL reflect the updated state.

#### Scenario: Candidate list loads and reviews

- **WHEN** an admin opens the ASR correction tab with pending LLM candidates present
- **THEN** the candidates SHALL be listed with approve and reject controls

#### Scenario: Approve removes candidate from pending list

- **WHEN** an admin approves a pending candidate
- **THEN** the candidate SHALL no longer appear in the pending list and SHALL appear as an active rule

<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->