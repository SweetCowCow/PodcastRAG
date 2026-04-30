## ADDED Requirements

### Requirement: Frontend exposes a responsive viewport hook

The frontend SHALL expose a shared hook `useViewport()` from `src/Shared.jsx` returning an object containing at minimum `{ isMobile: boolean }` where `isMobile` is `true` when `window.innerWidth < 768` and `false` otherwise. The hook SHALL initialize state synchronously from `window.innerWidth` on first render (not via `useEffect`) to avoid first-paint flicker. The hook SHALL register a `resize` event listener on `window` and update state when the viewport crosses the 768 px boundary. The listener SHALL be unregistered on component unmount.

The hook SHALL throttle resize updates by wrapping the state update in a single `requestAnimationFrame` callback so multiple resize events within a single frame trigger at most one re-render.

The hook SHALL be the single source of truth for `isMobile` across the application; components SHALL NOT call `window.innerWidth` directly for layout decisions.

#### Scenario: Initial render on mobile viewport

- **GIVEN** the page is loaded with `window.innerWidth = 390`
- **WHEN** a component calls `useViewport()` for the first time
- **THEN** the returned `isMobile` SHALL be `true` on the very first render (no flash of desktop layout)

#### Scenario: Initial render on desktop viewport

- **GIVEN** the page is loaded with `window.innerWidth = 1280`
- **WHEN** a component calls `useViewport()` for the first time
- **THEN** the returned `isMobile` SHALL be `false`

#### Scenario: Resize crosses breakpoint

- **GIVEN** a component is mounted with viewport at 1280 px
- **WHEN** the viewport is resized to 600 px
- **THEN** the hook SHALL update `isMobile` to `true` and the component SHALL re-render

#### Scenario: Resize within same band does not re-render

- **GIVEN** a component is mounted with viewport at 1280 px
- **WHEN** the viewport is resized to 1100 px (still desktop)
- **THEN** the hook MAY update internal state but SHALL NOT cause additional renders beyond what React already coalesces in the same frame (verified by no observable layout change)

#### Scenario: Listener cleanup on unmount

- **GIVEN** a component using `useViewport()` is unmounted
- **WHEN** the viewport is subsequently resized
- **THEN** no React warning about state updates on unmounted components SHALL occur

### Requirement: Top navigation collapses to hamburger menu on mobile

When `isMobile` is `true`, the top navigation (`TopNav` in `src/Shared.jsx`) SHALL render a single hamburger icon button (☰) anchored to the left of the title instead of the desktop horizontal flex bar of nav items. Clicking the hamburger SHALL toggle a dropdown panel that vertically lists the same primary nav items currently rendered in the desktop bar (節目選擇 / 後台管理 in zh, Podcasts / Admin in en) plus the language toggle button. Clicking any item in the dropdown SHALL close the dropdown.

When `isMobile` is `false`, the top navigation SHALL render the desktop horizontal flex bar exactly as today (no hamburger button).

Admin sub-tabs (API 金鑰 / LLM 模型 / RAG 設定 / 轉錄排程 / 轉錄序列 / 外部 API 狀態) are NOT collapsed into the hamburger; they SHALL remain in the page body and SHALL render as a horizontally scrollable flex bar (`overflow-x: auto`) when `isMobile` is `true`.

#### Scenario: Hamburger appears on mobile

- **GIVEN** the page is rendered with viewport at 390 px
- **WHEN** the user looks at the top of the page
- **THEN** a single ☰ icon button SHALL be visible at the left of the title
- **AND** the desktop horizontal nav items SHALL NOT be visible

#### Scenario: Desktop bar appears on desktop

- **GIVEN** the page is rendered with viewport at 1280 px
- **WHEN** the user looks at the top of the page
- **THEN** the desktop horizontal nav items SHALL be visible
- **AND** the hamburger ☰ button SHALL NOT be present

#### Scenario: Hamburger dropdown lists primary nav

- **GIVEN** mobile viewport
- **WHEN** the user clicks the ☰ button
- **THEN** a dropdown SHALL appear listing 節目選擇 / 後台管理 (zh) or Podcasts / Admin (en) plus the language toggle button

#### Scenario: Selecting an item closes the dropdown

- **GIVEN** the hamburger dropdown is open on mobile
- **WHEN** the user clicks 後台管理 / Admin
- **THEN** the page SHALL navigate to admin and the dropdown SHALL close

#### Scenario: Admin sub-tabs scroll horizontally on mobile

- **GIVEN** the admin page is open with mobile viewport
- **WHEN** the user looks at the sub-tab bar
- **THEN** the 6 sub-tabs SHALL render in a single horizontal flex row with `overflow-x: auto` allowing horizontal scroll
- **AND** the sub-tabs SHALL NOT wrap onto multiple lines

### Requirement: Form modals adapt width to viewport

The shared `FormModal` and `ConfirmModal` components in `src/Shared.jsx` SHALL render their inner box with width `min(95vw, 480)` (FormModal) or `min(95vw, 520)` (ConfirmModal) instead of the fixed `minWidth: 380 / 420`. On desktop viewports (≥ 768 px) this SHALL produce the same visual width as today (480 / 520 px). On mobile viewports (< 768 px) the modal SHALL never exceed 95% of the viewport width.

When `isMobile` is `true`, the inner box `padding` SHALL be reduced from `'22px 26px'` to `'18px 18px'`.

#### Scenario: Modal fits 360 px viewport

- **GIVEN** mobile viewport at 360 px
- **WHEN** a FormModal is opened
- **THEN** the modal inner box SHALL be at most 342 px wide (95% of 360) and SHALL NOT cause horizontal page scroll

#### Scenario: Modal preserves desktop width

- **GIVEN** desktop viewport at 1280 px
- **WHEN** a FormModal is opened
- **THEN** the modal inner box SHALL render at 480 px wide (same as today)

### Requirement: Touch targets meet 44 px minimum on mobile

When `isMobile` is `true`, all interactive elements (buttons, icon buttons, sub-tab triggers, segmented day picker, form select arrows, ↑/↓ reorder buttons, drawer toggle) SHALL have a minimum touch target of 44 × 44 CSS pixels. This applies to the visible button hit area (`min-height` and `min-width`); padding may be used to expand a smaller visual icon to satisfy the target.

When `isMobile` is `false`, existing button sizes (e.g., `Btn size="sm"` at ~30 px height) SHALL remain unchanged.

#### Scenario: Icon buttons grow on mobile

- **GIVEN** mobile viewport
- **WHEN** an icon button (e.g., expand chevron, ⋮ overflow menu) is rendered
- **THEN** its hit area SHALL be at least 44 × 44 px

#### Scenario: Desktop button sizes unchanged

- **GIVEN** desktop viewport
- **WHEN** a `Btn size="sm"` is rendered
- **THEN** its height SHALL remain ~30 px (no change from current)

### Requirement: Query page replaces split panel with overlay drawer on mobile

When `isMobile` is `true`, the query page (`src/QueryPage.jsx`) SHALL render the chat region at full viewport width and SHALL render the episode list panel as a fixed-position drawer overlaying the chat from the right edge. The drawer SHALL default to closed (`transform: translateX(100%)`). A drawer toggle icon button SHALL appear in the page header; clicking the toggle SHALL slide the drawer in (`transform: translateX(0)`) with a `transition: transform 0.18s ease-out`. While the drawer is open, a translucent overlay (`rgba(0,0,0,0.5)`) SHALL cover the chat region; clicking the overlay SHALL close the drawer.

The drawer width SHALL be `min(85vw, 360)`. The desktop resize handle SHALL NOT be rendered on mobile.

When `isMobile` is `false`, the query page SHALL render the desktop split panel layout exactly as today (chat + 340 px panel + resize handle).

#### Scenario: Drawer closed by default on mobile

- **GIVEN** mobile viewport, query page just navigated to
- **WHEN** the page renders
- **THEN** the chat region SHALL occupy the full viewport width
- **AND** the episode drawer SHALL NOT be visible (off-screen via translateX(100%))

#### Scenario: Toggle slides drawer in

- **GIVEN** mobile viewport, drawer is closed
- **WHEN** the user taps the drawer toggle button in the page header
- **THEN** the drawer SHALL slide in from the right within ~180 ms
- **AND** a translucent overlay SHALL appear over the chat region

#### Scenario: Overlay tap closes drawer

- **GIVEN** mobile viewport, drawer is open
- **WHEN** the user taps the overlay (outside the drawer)
- **THEN** the drawer SHALL slide out and the overlay SHALL disappear

#### Scenario: Desktop layout unchanged

- **GIVEN** desktop viewport
- **WHEN** the query page is rendered
- **THEN** the chat + 340 px panel + resize handle layout SHALL render exactly as today
- **AND** no drawer or toggle button SHALL be present

### Requirement: Form grid layouts collapse to single column on mobile

When `isMobile` is `true`, all form grid containers in `src/AdminPage.jsx` currently using `gridTemplateColumns: '1fr 1fr 1fr'` (the schedule create form's frequency / time / max-episodes row) SHALL render with `gridTemplateColumns: '1fr'`. The grid `gap` SHALL be reduced from 14 to 12.

When `isMobile` is `false`, the grid SHALL render `'1fr 1fr 1fr'` exactly as today.

#### Scenario: Three-column form stacks vertically on mobile

- **GIVEN** mobile viewport, admin schedule create form is shown
- **WHEN** the user views the frequency / run time / max-episodes row
- **THEN** the three fields SHALL render stacked vertically (one per row)

#### Scenario: Three-column form remains horizontal on desktop

- **GIVEN** desktop viewport
- **WHEN** the same form is shown
- **THEN** the three fields SHALL render side-by-side in a single row

