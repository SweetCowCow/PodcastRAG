## ADDED Requirements

### Requirement: Correction tables scroll horizontally on narrow viewports

Both tables in the ASR correction admin tab (the correction-rules list and the pending-candidates list) SHALL be wrapped in a container with `overflowX: 'auto'` so that on viewports narrower than the table's natural width every column remains reachable by horizontal scrolling. Each table SHALL declare a `minWidth` that keeps its columns readable instead of letting cells compress. No table content SHALL be clipped without a scrolling affordance.

#### Scenario: Rules table fully reachable on mobile

- **GIVEN** a 375 px-wide mobile viewport on the ASR correction tab with at least one rule whose row is wider than the viewport
- **WHEN** the rules table renders
- **THEN** the table's container SHALL scroll horizontally and the rightmost column (row actions) SHALL be reachable by scrolling

#### Scenario: Candidates table fully reachable on mobile

- **GIVEN** the same viewport with at least one pending candidate row wider than the viewport
- **WHEN** the pending-candidates table renders
- **THEN** the table's container SHALL scroll horizontally with no clipped-off, unreachable cells

#### Scenario: Desktop tables unchanged

- **GIVEN** a 1280 px desktop viewport where both tables fit their container
- **WHEN** the tab renders
- **THEN** no horizontal scrollbar SHALL appear and the layout SHALL match the pre-change desktop rendering
