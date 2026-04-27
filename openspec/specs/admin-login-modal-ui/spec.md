# admin-login-modal-ui Specification

## Purpose

TBD - created by archiving change 'remove-admin-login-demo-hint'. Update Purpose after archive.

## Requirements

### Requirement: Admin login modal SHALL NOT expose valid credentials in UI

The admin login modal SHALL NOT render any text, placeholder, tooltip, or helper note that reveals a working username or password (or any substring sufficient to recover one) for the admin account.

#### Scenario: Modal opens for an unauthenticated visitor

- **WHEN** an unauthenticated visitor opens the admin login modal
- **THEN** no element inside the modal SHALL display the strings `***REDACTED***`, `示範帳號`, or `Demo:` followed by credentials
- **AND** no helper text SHALL state or hint at the actual username/password pair required to authenticate

##### Example: previously-shown demo hint is gone

- **GIVEN** the modal is rendered in either Traditional Chinese or English locale
- **WHEN** the DOM under the modal root is inspected
- **THEN** it MUST NOT contain the substring `admin / ***REDACTED***`


<!-- @trace
source: remove-admin-login-demo-hint
updated: 2026-04-27
code:
  - src/App.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: Admin login modal SHALL keep its existing input and action affordances

The admin login modal SHALL continue to provide a username field, a password field, a submit ("Login") button, and a cancel button, with bilingual labels driven by the active language.

#### Scenario: Modal renders with required controls

- **WHEN** the modal is rendered
- **THEN** it MUST contain one username input, one password input, one submit button, and one cancel button
- **AND** the labels MUST switch between Traditional Chinese and English based on the `lang` prop

<!-- @trace
source: remove-admin-login-demo-hint
updated: 2026-04-27
code:
  - src/App.jsx
  - docs/case-studies/local-vs-prod-verification-violation.md
-->