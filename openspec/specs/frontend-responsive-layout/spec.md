# frontend-responsive-layout Specification

## Purpose

Defines the responsive layout system for PodcastRAG's frontend, including the shared `useViewport` hook, mobile-specific navigation, modal sizing, touch-target sizing, and layout adaptations across the query page and admin forms. The breakpoint between mobile and desktop is `window.innerWidth < 768`.

## Requirements

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


<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
code:
  - index.html
  - src/Shared.jsx
  - src/TranscriptPage.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/PodcastSelect.jsx
  - src/App.jsx
  - src/QueryPage.jsx
  - src/QueueTab.jsx
  - src/AdminPage.jsx
-->

---
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


<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
code:
  - index.html
  - src/Shared.jsx
  - src/TranscriptPage.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/PodcastSelect.jsx
  - src/App.jsx
  - src/QueryPage.jsx
  - src/QueueTab.jsx
  - src/AdminPage.jsx
-->

---
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


<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
code:
  - index.html
  - src/Shared.jsx
  - src/TranscriptPage.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/PodcastSelect.jsx
  - src/App.jsx
  - src/QueryPage.jsx
  - src/QueueTab.jsx
  - src/AdminPage.jsx
-->

---
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


<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
code:
  - index.html
  - src/Shared.jsx
  - src/TranscriptPage.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/PodcastSelect.jsx
  - src/App.jsx
  - src/QueryPage.jsx
  - src/QueueTab.jsx
  - src/AdminPage.jsx
-->

---
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


<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
code:
  - index.html
  - src/Shared.jsx
  - src/TranscriptPage.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/PodcastSelect.jsx
  - src/App.jsx
  - src/QueryPage.jsx
  - src/QueueTab.jsx
  - src/AdminPage.jsx
-->

---
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

<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
-->

<!-- @trace
source: responsive-mobile-layout
updated: 2026-05-01
code:
  - index.html
  - src/Shared.jsx
  - src/TranscriptPage.jsx
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/PodcastSelect.jsx
  - src/App.jsx
  - src/QueryPage.jsx
  - src/QueueTab.jsx
  - src/AdminPage.jsx
-->

---
### Requirement: Landing Page is responsive between mobile and desktop

The Landing Page SHALL adapt its layout based on the shared `useViewport` hook breakpoint at `window.innerWidth < 768`. On desktop (>= 768 px wide):

- The hero section search input and CTA button SHALL be on the same horizontal row.
- The collected-shows grid SHALL display 3 columns.
- The paywall band SHALL center in a max-width 720 px container.

On mobile (< 768 px wide):

- The hero CTA button SHALL stack below the search input.
- The collected-shows grid SHALL collapse to 1 column with full-width cards.
- The paywall band SHALL span 90% of the viewport width.

#### Scenario: Desktop layout uses 3-column grid

- **GIVEN** a viewport of 1024×768
- **WHEN** Landing renders
- **THEN** the collected-shows section SHALL render exactly 3 cards per row (assuming >=3 shows)

#### Scenario: Mobile layout stacks to 1 column

- **GIVEN** a viewport of 375×667
- **WHEN** Landing renders
- **THEN** the collected-shows section SHALL render 1 card per row
- **AND** the hero CTA SHALL appear below the search input on its own row

#### Scenario: Resize switches layout live

- **GIVEN** Landing is rendered at viewport width 1024
- **WHEN** the user resizes the window to width 600
- **THEN** the layout SHALL update to the mobile arrangement without reload


<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->

---
### Requirement: QueryPage shows quota meter and unlock card states

The QueryPage SHALL display, in a status bar above the search input area:

- For authenticated users: a quota progress meter showing `已用 X / 共 Y`, a horizontal progress bar visualizing `quota_remaining / quota_initial`, and a button labelled `申請更多額度 →` (`zh`) / `Request more quota →` (`en`) that opens the QuotaApplyModal. The button SHALL render unconditionally — no quota threshold gates its visibility.
- For unauthenticated users: the meter SHALL NOT render. Instead, no status bar SHALL appear in this slot.

When the user submits a query and an LLM-answer area is rendered:

- For authenticated users: the answer card SHALL render the LLM answer normally (driven by the chat endpoint).
- For unauthenticated users: a locked card SHALL render in the answer position with text `🔒 想看 AI 整段統整？` (`zh`) / `🔒 Want the AI summary?` (`en`), a body line `不用一段段拼湊。` (`zh`) / `Skip stitching segments together.` (`en`), and a primary button `以 Google 登入解鎖` (`zh`) / `Sign in with Google to unlock` (`en`) below which the line `30 次免費` (`zh`) / `30 free uses` (`en`) appears in smaller secondary text. The locked card height SHALL be capped at 200 px to keep the segment results visible without forced scrolling.

#### Scenario: Authenticated user sees meter

- **GIVEN** an authenticated user with `quota_initial=30, quota_remaining=18`
- **WHEN** QueryPage renders
- **THEN** the status bar SHALL display `12 / 30 已用` (or equivalent) and a progress bar at 40 %
- **AND** the `申請更多額度 →` button SHALL be visible

#### Scenario: Unauthenticated user does not see meter

- **WHEN** an unauthenticated visitor lands on QueryPage
- **THEN** no quota meter SHALL render
- **AND** no `申請更多額度` button SHALL be present

#### Scenario: Unauthenticated user sees locked answer card

- **GIVEN** an unauthenticated visitor on QueryPage
- **WHEN** the visitor submits a search query and the response returns segments
- **THEN** the LLM-answer area SHALL render the locked card with the specified copy
- **AND** the segment results SHALL render below the locked card
- **AND** the locked card height SHALL not exceed 200 px

#### Scenario: Locked card login button opens LoginModal

- **WHEN** the visitor clicks `以 Google 登入解鎖` on the locked card
- **THEN** the existing `LoginModal` SHALL open

#### Scenario: After login, locked card disappears and answer renders

- **GIVEN** the visitor was on QueryPage with the locked card rendered
- **WHEN** the visitor completes Google login (LoginModal closes successfully)
- **THEN** the page SHALL re-resolve auth state and render the LLM-answer area for the existing query
- **AND** the locked card SHALL no longer render


<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->

---
### Requirement: QuotaApplyModal collects and submits quota request

The frontend SHALL provide a `QuotaApplyModal` component opened by the `申請更多額度 →` button. The modal SHALL contain: a heading `申請更多額度` (`zh`) / `Request more quota` (`en`), a `<textarea>` labelled `請告訴我們你的用途`(`zh`) / `Tell us how you'll use it` (`en`) with `minLength=10, maxLength=1000`, a primary submit button `送出申請` (`zh`) / `Submit request` (`en`), and a cancel button. On open, the modal SHALL `GET /quota-requests/me?status=pending`; if a pending row exists, the modal SHALL render an alternative state showing `您已有一筆審核中的申請（送出於 <date>）` (`zh`) / `You already have a pending request (submitted <date>)` (`en`) with no textarea or submit button — only an OK / close button. On submit (when no pending row exists), the modal SHALL `POST /quota-requests` with the textarea body; on HTTP 201 the modal SHALL show `已送出，admin 收到通知後會處理` (`zh`) / `Submitted — admin will be notified.` (`en`) for ~2 seconds then close. On HTTP 409 (`quota_request_pending`) the modal SHALL re-render the pending state. On HTTP 422 (validation) the modal SHALL show inline error under the textarea.

#### Scenario: First-time submit shows success then closes

- **GIVEN** an authenticated user with no pending quota_request
- **WHEN** the user opens the modal, types `我做研究需要更多 quota`, and clicks submit
- **THEN** the POST `/quota-requests` SHALL fire with that body
- **AND** on HTTP 201 a success message SHALL display
- **AND** the modal SHALL auto-close after approximately 2 seconds

#### Scenario: Existing pending request renders blocked state

- **GIVEN** the user already has one pending quota_request submitted at `2026-05-04 10:00 UTC`
- **WHEN** the user opens the modal
- **THEN** the modal SHALL render the blocked state with the submitted date
- **AND** SHALL NOT render the textarea or submit button

#### Scenario: Reason too short shows inline error

- **WHEN** the user types `太短`(4 chars) and clicks submit
- **THEN** the modal SHALL show an inline validation error and NOT call the API

<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->