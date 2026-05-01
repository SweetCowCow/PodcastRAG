# release-log-ui Specification

## Purpose

TBD - created by archiving change 'release-log-and-presentation'. Update Purpose after archive.

## Requirements

### Requirement: Release Log Page Navigation

The system SHALL expose a Release Log page accessible from the top navigation bar, available without authentication.

#### Scenario: User opens release log from top nav

- **WHEN** the user clicks the "Release Log" / "更新日誌" link in TopNav
- **THEN** the application sets `page` state to `'release-log'` and renders the ReleaseLogPage component

#### Scenario: Release log respects current language

- **WHEN** the user toggles language between zh and en while on the release log page
- **THEN** all entry titles, summaries, milestone labels, and tag labels switch to the corresponding language without page reload


<!-- @trace
source: release-log-and-presentation
updated: 2026-05-01
code:
  - CLAUDE.md
  - src/ReleaseLogPage.jsx
  - src/Shared.jsx
  - src/PresentationPage.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - index.html
  - src/App.jsx
  - src/releaseLog.jsx
-->

---
### Requirement: Release Log Entry Listing

The system SHALL display all release log entries grouped by milestone, with milestones and entries within each milestone sorted in reverse chronological order (newest first).

#### Scenario: Entries grouped by milestone

- **WHEN** the release log page renders
- **THEN** entries are grouped under milestone headings (e.g., "v0.4", "v0.3", "v0.2", "v0.1")
- **AND** milestones appear in reverse version order
- **AND** within each milestone, entries are sorted by `date` descending

#### Scenario: Entry displays date, tag badge, title, summary

- **WHEN** an entry is rendered
- **THEN** the entry shows the formatted date, a colored tag Badge (feature / fix / enhancement / ui), the localized title, and the localized summary

##### Example: entry layout

| Field | Source | Display |
| ----- | ------ | ------- |
| date | `entry.date` | "2026-05-01" |
| tag | `entry.tag` | Badge with variant mapping (feature→success, fix→warning, enhancement→default, ui→muted) |
| title | `entry.title[lang]` | bold, larger font |
| summary | `entry.summary[lang]` | regular, secondary text color |


<!-- @trace
source: release-log-and-presentation
updated: 2026-05-01
code:
  - CLAUDE.md
  - src/ReleaseLogPage.jsx
  - src/Shared.jsx
  - src/PresentationPage.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - index.html
  - src/App.jsx
  - src/releaseLog.jsx
-->

---
### Requirement: Single Source of Truth for Release Data

The system SHALL store all release log entries in a single module `src/releaseLog.jsx` exporting an array constant, consumed by both the Release Log page and the Presentation page.

#### Scenario: Entry shape

- **WHEN** an entry is added to the array
- **THEN** the entry conforms to: `{ date: string (YYYY-MM-DD), slug: string, milestone: string, tag: 'feature'|'fix'|'enhancement'|'ui', title: { zh: string, en: string }, summary: { zh: string, en: string } }`

#### Scenario: Initial backfill

- **WHEN** the module is first created
- **THEN** the array contains exactly 24 entries corresponding to the 24 archived changes in `openspec/changes/archive/` between 2026-04-19 and 2026-05-01


<!-- @trace
source: release-log-and-presentation
updated: 2026-05-01
code:
  - CLAUDE.md
  - src/ReleaseLogPage.jsx
  - src/Shared.jsx
  - src/PresentationPage.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - index.html
  - src/App.jsx
  - src/releaseLog.jsx
-->

---
### Requirement: Stats Snapshot Constant

The system SHALL export a `STATS_AS_OF` date constant alongside numeric snapshot values from `src/releaseLog.jsx` so the Presentation page can show "as of YYYY-MM-DD".

#### Scenario: Stats constants exported

- **WHEN** `releaseLog.jsx` is loaded
- **THEN** the module exports `STATS_AS_OF` (string), `STATS_CHANGES_COUNT` (number), `STATS_EPISODES_COUNT` (number), and `STATS_VECTORS_COUNT` (number)

<!-- @trace
source: release-log-and-presentation
updated: 2026-05-01
code:
  - CLAUDE.md
  - src/ReleaseLogPage.jsx
  - src/Shared.jsx
  - src/PresentationPage.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
  - docs/case-studies/transcription-queue-discussion.md
  - index.html
  - src/App.jsx
  - src/releaseLog.jsx
-->