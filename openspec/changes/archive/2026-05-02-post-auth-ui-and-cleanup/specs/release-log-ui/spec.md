## ADDED Requirements

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

### Requirement: Milestone section markers appear inline on the timeline

When rendering, the timeline SHALL insert a milestone marker between entries whenever consecutive entries belong to different milestones. The marker SHALL display the milestone label (e.g., "v0.4 — 手機版與友善錯誤" / "v0.4 — Mobile & Friendly Errors") visually distinct from entry nodes (e.g., enlarged label, divider line, or band).

#### Scenario: Milestone marker rendered between adjacent milestones

- **WHEN** entry N has milestone `'v0.5'` and entry N+1 has milestone `'v0.4'`
- **THEN** a milestone marker labelled with `MILESTONE_LABELS['v0.4']` SHALL render between them

#### Scenario: No marker before first entry of the same milestone group

- **WHEN** entry N and entry N+1 both have milestone `'v0.4'`
- **THEN** no milestone marker SHALL render between them

### Requirement: Mobile timeline collapses to left-aligned variant

On viewports below 768px, the timeline SHALL render with the vertical line aligned at the left edge (not centred), and entry cards SHALL occupy the full remaining horizontal width. Nodes SHALL remain on the line.

#### Scenario: Mobile rendering

- **WHEN** the page is viewed at viewport width below 768px
- **THEN** the vertical line SHALL render at the left edge of the entries area
- **AND** each entry card SHALL stretch to use the full remaining row width
