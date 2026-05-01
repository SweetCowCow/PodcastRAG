## ADDED Requirements

### Requirement: Hash-Based Presentation Routing

The system SHALL render the Presentation page when the URL hash equals `#presentation`, and exit when the hash is cleared. The Presentation page MUST NOT have any entry point in TopNav or other pages.

#### Scenario: User enters presentation via URL hash

- **WHEN** the URL hash changes to `#presentation` (manual edit or deep link)
- **THEN** the application sets `page` state to `'presentation'` and renders the PresentationPage component fullscreen
- **AND** TopNav and other chrome are hidden during presentation

#### Scenario: Esc key exits presentation

- **WHEN** the user is on the Presentation page and presses `Escape`
- **THEN** the URL hash is cleared and the application returns to the previous page

#### Scenario: TopNav has no presentation entry

- **WHEN** any non-presentation page is rendered
- **THEN** TopNav contains no link, button, or menu item that navigates to `#presentation`

### Requirement: Slide Deck Structure

The Presentation page SHALL render exactly 13 slides in this order: cover, system intro, architecture diagram, four milestone slides (v0.1 → v0.4), stats snapshot, three case-study slides, next steps, closing.

#### Scenario: Slide order is fixed

- **WHEN** the presentation initially loads
- **THEN** slide index 0 is the cover slide and slide index 12 is the closing slide
- **AND** indices 3, 4, 5, 6 correspond to milestones v0.1, v0.2, v0.3, v0.4 in ascending order

#### Scenario: Milestone slide content is data-driven

- **WHEN** a milestone slide for `v0.x` renders
- **THEN** the slide lists every entry from `releaseLog.jsx` where `entry.milestone === 'v0.x'`, sorted by date ascending
- **AND** each entry shows date + title (zh) + tag badge

#### Scenario: Stats slide displays snapshot values

- **WHEN** the stats slide renders
- **THEN** the slide shows `STATS_CHANGES_COUNT`, `STATS_EPISODES_COUNT`, `STATS_VECTORS_COUNT` from `releaseLog.jsx`
- **AND** displays "截至 {STATS_AS_OF}" disclaimer

### Requirement: Keyboard Navigation

The Presentation page SHALL support keyboard navigation between slides via arrow keys and spacebar.

#### Scenario: Right arrow advances slide

- **WHEN** the user presses `ArrowRight` or `Space` on a non-final slide
- **THEN** the current slide index increments by 1

#### Scenario: Left arrow goes back

- **WHEN** the user presses `ArrowLeft` on a non-first slide
- **THEN** the current slide index decrements by 1

#### Scenario: Boundary behavior

- **WHEN** the user presses `ArrowRight` on slide index 12 (closing)
- **THEN** the slide index does not change

- **WHEN** the user presses `ArrowLeft` on slide index 0 (cover)
- **THEN** the slide index does not change

### Requirement: Case Study Slides Inline Content

The three case-study slides SHALL contain content authored inline within the PresentationPage component (not loaded from `docs/case-studies/` at runtime), each summarizing one case study in three lines: problem, turning point, lesson learned.

#### Scenario: Case study content is inline

- **WHEN** the PresentationPage component is rendered
- **THEN** the three case-study slides reference content defined as constants within the component file, not via fetch or import from `docs/case-studies/`

### Requirement: Presentation is Chinese-Only

The Presentation page SHALL render in Traditional Chinese regardless of the application's current `lang` state.

#### Scenario: Language toggle does not affect presentation

- **WHEN** the application `lang` is `'en'` and the user enters `#presentation`
- **THEN** all slide text renders in Traditional Chinese
