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

---
### Requirement: Release log entries render as a single vertical timeline

The Release Log page SHALL render entries as a single vertical timeline. The timeline SHALL consist of one continuous vertical line, with one node (filled circle) per entry positioned on the line. Each entry's metadata (title, summary, tag badge, milestone) SHALL render as a card aligned to the right of its node. Entries SHALL appear in newest-first order across the entire page.

#### Scenario: Page renders timeline structure

- **WHEN** an authenticated or unauthenticated visitor opens the Release Log page
- **THEN** the page SHALL render exactly one continuous vertical line element along the left side of the entry list
- **AND** each entry from `RELEASE_LOG` SHALL be represented by exactly one node on the line
- **AND** each entry's title and summary SHALL render in a card to the right of its node

#### Scenario: Entries appear newest-first across all milestones

- **WHEN** the timeline renders entries from multiple milestones (e.g., v0.5, v0.4, v0.3)
- **THEN** the topmost entry SHALL be the one with the most recent `date` field across all entries
- **AND** subsequent entries SHALL appear in descending `date` order

##### Example: ordering across milestones

- **GIVEN** entries with dates 2026-05-02 (v0.5), 2026-05-01 (v0.4), 2026-04-30 (v0.4), 2026-04-28 (v0.3)
- **WHEN** the page renders
- **THEN** the top-to-bottom order is exactly: 2026-05-02, 2026-05-01, 2026-04-30, 2026-04-28


<!-- @trace
source: post-auth-ui-and-cleanup
updated: 2026-05-02
code:
  - src/App.jsx
  - src/QueueTab.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - src/ReleaseLogPage.jsx
  - backend/app/main.py
  - index.html
  - src/AuthContext.jsx
  - src/PodcastSelect.jsx
  - backend/app/api/stats.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/stats.py
  - src/i18n.jsx
tests:
  - backend/tests/test_admin_stats.py
  - backend/tests/test_queue_reorder.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_cron_tick_stale.py
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_status_endpoints.py
  - backend/tests/conftest.py
  - backend/tests/test_queue_cancel.py
-->

---
### Requirement: Milestone section markers appear inline on the timeline

When rendering, the timeline SHALL insert a milestone marker between entries whenever consecutive entries belong to different milestones. The marker SHALL display the milestone label (e.g., "v0.4 — 手機版與友善錯誤" / "v0.4 — Mobile & Friendly Errors") visually distinct from entry nodes (e.g., enlarged label, divider line, or band).

#### Scenario: Milestone marker rendered between adjacent milestones

- **WHEN** entry N has milestone `'v0.5'` and entry N+1 has milestone `'v0.4'`
- **THEN** a milestone marker labelled with `MILESTONE_LABELS['v0.4']` SHALL render between them

#### Scenario: No marker before first entry of the same milestone group

- **WHEN** entry N and entry N+1 both have milestone `'v0.4'`
- **THEN** no milestone marker SHALL render between them


<!-- @trace
source: post-auth-ui-and-cleanup
updated: 2026-05-02
code:
  - src/App.jsx
  - src/QueueTab.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - src/ReleaseLogPage.jsx
  - backend/app/main.py
  - index.html
  - src/AuthContext.jsx
  - src/PodcastSelect.jsx
  - backend/app/api/stats.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/stats.py
  - src/i18n.jsx
tests:
  - backend/tests/test_admin_stats.py
  - backend/tests/test_queue_reorder.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_cron_tick_stale.py
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_status_endpoints.py
  - backend/tests/conftest.py
  - backend/tests/test_queue_cancel.py
-->

---
### Requirement: Mobile timeline collapses to left-aligned variant

On viewports below 768px, the timeline SHALL render with the vertical line aligned at the left edge (not centred), and entry cards SHALL occupy the full remaining horizontal width. Nodes SHALL remain on the line.

#### Scenario: Mobile rendering

- **WHEN** the page is viewed at viewport width below 768px
- **THEN** the vertical line SHALL render at the left edge of the entries area
- **AND** each entry card SHALL stretch to use the full remaining row width

<!-- @trace
source: post-auth-ui-and-cleanup
updated: 2026-05-02
code:
  - src/App.jsx
  - src/QueueTab.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - src/ReleaseLogPage.jsx
  - backend/app/main.py
  - index.html
  - src/AuthContext.jsx
  - src/PodcastSelect.jsx
  - backend/app/api/stats.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/schemas/stats.py
  - src/i18n.jsx
tests:
  - backend/tests/test_admin_stats.py
  - backend/tests/test_queue_reorder.py
  - backend/tests/test_error_responses.py
  - backend/tests/test_cron_tick_stale.py
  - backend/tests/test_transcribe_task_celery_id.py
  - backend/tests/test_status_endpoints.py
  - backend/tests/conftest.py
  - backend/tests/test_queue_cancel.py
-->