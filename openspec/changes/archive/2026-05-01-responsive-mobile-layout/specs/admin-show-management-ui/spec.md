## ADDED Requirements

### Requirement: Schedule modal renders mobile-friendly layout

When `isMobile` is `true`, the schedule edit/create modal in `src/AdminPage.jsx` SHALL render its inner box with `width: min(95vw, 480)` (inheriting the shared `FormModal` mobile width). Internal field rows that use `gridTemplateColumns: '1fr 1fr 1fr'` on desktop SHALL collapse to `gridTemplateColumns: '1fr'` on mobile. The day_of_week segmented button group SHALL retain `flexWrap: 'wrap'` (already present); each day button SHALL have minimum touch target of 44 × 44 px. The Whisper model selector buttons SHALL retain `flexWrap: 'wrap'`.

When `isMobile` is `false`, the schedule modal SHALL render exactly as today (desktop layout, fixed grid columns, current button sizes).

#### Scenario: Modal fits 360 px viewport

- **GIVEN** mobile viewport at 360 px, schedule edit modal is opened
- **WHEN** the modal renders
- **THEN** the inner box width SHALL be at most 342 px (95% of 360)
- **AND** no field SHALL cause horizontal scroll within the modal

#### Scenario: Three-column row stacks on mobile

- **GIVEN** mobile viewport, schedule edit modal is opened
- **WHEN** the user views internal field rows that span three columns on desktop
- **THEN** the fields SHALL render stacked vertically (one per row)

#### Scenario: Day picker buttons meet touch target

- **GIVEN** mobile viewport, schedule edit modal with frequency=weekly
- **WHEN** the day_of_week segmented buttons render
- **THEN** each button SHALL have a hit area of at least 44 × 44 px

#### Scenario: Desktop modal unchanged

- **GIVEN** desktop viewport, schedule edit modal is opened
- **WHEN** the modal renders
- **THEN** the inner box SHALL render at 480 px wide
- **AND** three-column rows SHALL render side-by-side as today

### Requirement: Schedule cards stack vertically on mobile

When `isMobile` is `true`, each schedule card in the admin schedule list (`src/AdminPage.jsx`) SHALL render its content in a vertical stack: header (checkbox + title + badges) on top, metadata row (RSS URL / frequency / last refresh / whisper model) directly below, and action buttons (查看進度 / 立刻執行轉錄 / 更多操作) on a wrapped row at the bottom. The metadata row SHALL retain `flexWrap: 'wrap'` so individual metadata items wrap as needed. The action button area SHALL change from `flexShrink: 0` (desktop, never shrinks) to `flexWrap: 'wrap'` allowing buttons to wrap onto multiple lines.

The card outer container border, background, and `padding: '18px 22px'` SHALL be reduced on mobile to `padding: '14px 16px'` to give content more room.

When `isMobile` is `false`, schedule cards SHALL render exactly as today (single horizontal flex row with fixed action area on the right).

#### Scenario: Card stacks on mobile

- **GIVEN** mobile viewport, admin schedule list renders 3 shows
- **WHEN** the user views one card
- **THEN** the title row, metadata row, and action button row SHALL render stacked vertically (one above the other)

#### Scenario: Action buttons wrap on mobile

- **GIVEN** mobile viewport, a schedule card has 3 action buttons
- **WHEN** the buttons would not fit on a single row
- **THEN** they SHALL wrap onto multiple rows (no horizontal overflow)

#### Scenario: Desktop card unchanged

- **GIVEN** desktop viewport
- **WHEN** the schedule list renders
- **THEN** each card SHALL render as a single horizontal flex row with the action button area fixed on the right (no shrink)

