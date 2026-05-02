# admin-login-modal-ui Specification

## Purpose

TBD - created by archiving change 'remove-admin-login-demo-hint'. Update Purpose after archive.

## Requirements

### Requirement: Admin login modal SHALL NOT expose valid credentials in UI

The frontend SHALL NOT render any text, placeholder, tooltip, helper note, or hardcoded string anywhere in the bundle that reveals a working username or password (or any substring sufficient to recover one) for any admin account. Because authentication has moved to Google SSO, the application SHALL NOT contain any local password comparison string in source code.

#### Scenario: Bundle contains no hardcoded admin credential

- **WHEN** the frontend source files (`src/**/*.jsx`, `index.html`) are searched for the strings `***REDACTED***`, `***REDACTED***`, `示範帳號`, or `Demo:` followed by credentials
- **THEN** no occurrence SHALL be found
- **AND** no JavaScript expression SHALL compare a user-entered password against a string literal

##### Example: previously-shown demo hint is gone

- **GIVEN** the application is rendered in either Traditional Chinese or English locale
- **WHEN** the DOM and the page-loaded JavaScript are inspected
- **THEN** they MUST NOT contain the substrings `admin / ***REDACTED***` or `admin / ***REDACTED***`


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Top navigation provides Google sign-in entry point

The top navigation bar SHALL render a "Sign in with Google" / "使用 Google 登入" button when no authenticated session exists. Clicking the button SHALL navigate the browser to the backend endpoint `GET /auth/google/start` (full URL constructed from the configured backend base URL).

#### Scenario: Unauthenticated visitor sees the sign-in button

- **WHEN** the application loads without a valid session cookie
- **THEN** the top navigation bar SHALL contain exactly one element labeled "Sign in with Google" or "使用 Google 登入" (depending on active language)
- **AND** the element SHALL navigate to `<BACKEND_BASE_URL>/auth/google/start` when clicked

#### Scenario: Authenticated visitor does not see the sign-in button

- **WHEN** the application loads with a valid session cookie and `GET /me` returns a user payload
- **THEN** the top navigation bar SHALL NOT render the sign-in button
- **AND** SHALL render the user's avatar, name, remaining quota, and a logout affordance instead

<!-- @trace
source: authentication-system
updated: 2026-05-02
-->


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Admin section is gated by authenticated admin role

The frontend admin section (any page whose path starts with `admin-`) SHALL only render when the authenticated user's `role` is `admin` and `status` is `active`. Unauthenticated users SHALL be redirected to the sign-in flow; authenticated members SHALL be redirected to the public landing page.

#### Scenario: Member tries to navigate to admin URL

- **WHEN** a user with `role='member'` triggers navigation to any `admin-*` page
- **THEN** the admin pages SHALL NOT render
- **AND** the user SHALL be redirected to the `select` page

#### Scenario: Unauthenticated user clicks admin nav

- **WHEN** an unauthenticated user clicks the admin navigation link
- **THEN** the browser SHALL be navigated to the backend Google sign-in endpoint

<!-- @trace
source: authentication-system
updated: 2026-05-02
-->

<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->