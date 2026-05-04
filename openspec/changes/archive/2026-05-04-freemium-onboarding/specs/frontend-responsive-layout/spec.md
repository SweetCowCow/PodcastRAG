## ADDED Requirements

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
