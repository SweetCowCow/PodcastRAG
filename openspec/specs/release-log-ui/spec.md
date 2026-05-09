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

The system SHALL display all release log entries grouped by milestone, with milestones and entries within each milestone sorted in reverse chronological order (newest first). Each entry SHALL render as a header row (always visible) plus a collapsible body region (hidden by default; see Entry Body Collapsed By Default With Click-To-Expand).

#### Scenario: Entries grouped by milestone

- **WHEN** the release log page renders
- **THEN** entries are grouped under milestone headings (e.g., "v1.4", "v1.0", "v0.9")
- **AND** milestones appear in reverse version order
- **AND** within each milestone, entries are sorted by `date` descending

#### Scenario: Header row displays date, tag badge, title, summaryBullets, chevron

- **WHEN** an entry is rendered
- **THEN** the entry's header row SHALL show the formatted date, a colored tag Badge (feature / fix / enhancement / ui), the localized title, the localized `summaryBullets` (when present), and a chevron / disclosure icon indicating collapsed or expanded state

##### Example: header row layout

| Field | Source | Display |
| ----- | ------ | ------- |
| date | `entry.date` | "2026-05-04" |
| tag | `entry.tag` | Badge with variant mapping (feature→success, fix→warning, enhancement→default, ui→muted) |
| title | `entry.title[lang]` | bold, larger font |
| summaryBullets | `entry.summaryBullets[lang]` | `<ul>` of 2-4 short `<li>` bullets, secondary text color |
| chevron | derived from local expanded state | rotates 90° when expanded |

#### Scenario: Body region holds existing detail content

- **WHEN** the entry body is expanded
- **THEN** the body SHALL render the existing localized `summary` text (and any future detail markup) immediately below the header row


<!-- @trace
source: release-log-collapsible-with-summary
updated: 2026-05-09
code:
  - src/releaseLog.jsx
  - backend/scripts/backfill_topic_labels.py
  - src/ReleaseLogPage.jsx
-->

---
### Requirement: Single Source of Truth for Release Data

The system SHALL store all release log entries in a single module `src/releaseLog.jsx` exporting an array constant, consumed by both the Release Log page and the Presentation page.

#### Scenario: Entry shape

- **WHEN** an entry is added to the array
- **THEN** the entry conforms to: `{ date: string (YYYY-MM-DD), slug: string, milestone: string, tag: 'feature'|'fix'|'enhancement'|'ui', title: { zh: string, en: string }, summary: { zh: string, en: string }, summaryBullets?: { zh: string[], en: string[] } }`
- **AND** `summaryBullets`, when present, SHALL contain 2 to 4 strings in each language

#### Scenario: Initial backfill

- **WHEN** the module is first created
- **THEN** the array contains exactly 24 entries corresponding to the 24 archived changes in `openspec/changes/archive/` between 2026-04-19 and 2026-05-01

#### Scenario: summaryBullets backfill scope

- **WHEN** this change ships
- **THEN** the v1.4 entry SHALL include a populated `summaryBullets` field as a worked example
- **AND** older entries MAY retain no `summaryBullets` field; the renderer SHALL handle that case per the "Entry without summaryBullets degrades gracefully" scenario


<!-- @trace
source: release-log-collapsible-with-summary
updated: 2026-05-09
code:
  - src/releaseLog.jsx
  - backend/scripts/backfill_topic_labels.py
  - src/ReleaseLogPage.jsx
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

---
### Requirement: Entry Body Collapsed By Default With Click-To-Expand

The system SHALL render every Release Log entry with a fixed header row (always visible) and a collapsible body region (hidden by default). Clicking anywhere on the header row SHALL toggle the body visibility for that entry.

#### Scenario: Initial page render hides all bodies

- **WHEN** the user opens the Release Log page without a URL hash
- **THEN** every entry SHALL render with its body region hidden
- **AND** only the header row of each entry SHALL be visible

#### Scenario: Click header toggles body

- **WHEN** the user clicks an entry's header row while its body is hidden
- **THEN** the body region for that entry SHALL become visible
- **AND** the chevron / disclosure icon in the header SHALL rotate to indicate expanded state
- **WHEN** the user clicks the same header row again
- **THEN** the body region SHALL collapse back to hidden
- **AND** the chevron SHALL return to the collapsed orientation

#### Scenario: Each entry tracks expanded state independently

- **WHEN** the user expands entry A and then expands entry B
- **THEN** both entry A and entry B SHALL remain expanded
- **AND** other entries SHALL remain collapsed


<!-- @trace
source: release-log-collapsible-with-summary
updated: 2026-05-09
code:
  - src/releaseLog.jsx
  - backend/scripts/backfill_topic_labels.py
  - src/ReleaseLogPage.jsx
-->

---
### Requirement: Header Row Shows Summary Bullets

The system SHALL render an entry's `summaryBullets` (when provided) as a bulleted list inside the header row, beneath the title and metadata. The list SHALL contain 2 to 4 short bullets in the user's currently selected language.

#### Scenario: Entry with summaryBullets renders bullets in header

- **WHEN** an entry's data contains `summaryBullets: { zh: [...], en: [...] }` with 2 to 4 items
- **THEN** the header row SHALL render those items as a `<ul>` of `<li>` bullets in the active language
- **AND** the bullets SHALL be visible regardless of whether the body is expanded or collapsed

#### Scenario: Entry without summaryBullets degrades gracefully

- **WHEN** an entry's data does NOT contain `summaryBullets` (or it is `null` / empty array)
- **THEN** the header row SHALL render only the existing title, date, milestone, and tag — no empty bullet list area


<!-- @trace
source: release-log-collapsible-with-summary
updated: 2026-05-09
code:
  - src/releaseLog.jsx
  - backend/scripts/backfill_topic_labels.py
  - src/ReleaseLogPage.jsx
-->

---
### Requirement: URL Hash Auto-Expands Targeted Entry

The system SHALL auto-expand the entry whose `slug` matches the current URL hash when the page loads, and SHALL scroll that entry into view.

#### Scenario: Page opened with hash auto-expands matching entry

- **WHEN** the user opens `/release-log#v1-4-freemium-launch` (where `v1-4-freemium-launch` is an existing entry slug)
- **THEN** that entry's body SHALL render expanded on first paint
- **AND** the page SHALL scroll the entry into the viewport

#### Scenario: Hash with unknown slug leaves all collapsed

- **WHEN** the user opens `/release-log#non-existent-slug`
- **THEN** all entries SHALL remain collapsed
- **AND** no scroll behavior SHALL occur


<!-- @trace
source: release-log-collapsible-with-summary
updated: 2026-05-09
code:
  - src/releaseLog.jsx
  - backend/scripts/backfill_topic_labels.py
  - src/ReleaseLogPage.jsx
-->

---
### Requirement: Header Row Is Keyboard Accessible

The system SHALL render each entry's header row as a focusable, button-like control. Pressing `Enter` or `Space` while the header has keyboard focus SHALL toggle the body visibility identically to a mouse click.

#### Scenario: Tab navigation reaches each header

- **WHEN** the user presses `Tab` repeatedly on the Release Log page
- **THEN** focus SHALL traverse each entry's header row in document order
- **AND** the focused header SHALL render a visible focus outline

#### Scenario: Enter / Space toggles body

- **WHEN** an entry's header has keyboard focus and the user presses `Enter` or `Space`
- **THEN** that entry's body SHALL toggle between hidden and visible

<!-- @trace
source: release-log-collapsible-with-summary
updated: 2026-05-09
code:
  - src/releaseLog.jsx
  - backend/scripts/backfill_topic_labels.py
  - src/ReleaseLogPage.jsx
-->