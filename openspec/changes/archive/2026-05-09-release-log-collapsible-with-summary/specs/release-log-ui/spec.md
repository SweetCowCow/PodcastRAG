## ADDED Requirements

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

### Requirement: Header Row Shows Summary Bullets

The system SHALL render an entry's `summaryBullets` (when provided) as a bulleted list inside the header row, beneath the title and metadata. The list SHALL contain 2 to 4 short bullets in the user's currently selected language.

#### Scenario: Entry with summaryBullets renders bullets in header

- **WHEN** an entry's data contains `summaryBullets: { zh: [...], en: [...] }` with 2 to 4 items
- **THEN** the header row SHALL render those items as a `<ul>` of `<li>` bullets in the active language
- **AND** the bullets SHALL be visible regardless of whether the body is expanded or collapsed

#### Scenario: Entry without summaryBullets degrades gracefully

- **WHEN** an entry's data does NOT contain `summaryBullets` (or it is `null` / empty array)
- **THEN** the header row SHALL render only the existing title, date, milestone, and tag — no empty bullet list area

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

### Requirement: Header Row Is Keyboard Accessible

The system SHALL render each entry's header row as a focusable, button-like control. Pressing `Enter` or `Space` while the header has keyboard focus SHALL toggle the body visibility identically to a mouse click.

#### Scenario: Tab navigation reaches each header

- **WHEN** the user presses `Tab` repeatedly on the Release Log page
- **THEN** focus SHALL traverse each entry's header row in document order
- **AND** the focused header SHALL render a visible focus outline

#### Scenario: Enter / Space toggles body

- **WHEN** an entry's header has keyboard focus and the user presses `Enter` or `Space`
- **THEN** that entry's body SHALL toggle between hidden and visible

## MODIFIED Requirements

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
