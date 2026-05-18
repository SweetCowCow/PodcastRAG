## ADDED Requirements

### Requirement: Lock card shows disabled state with appeal CTA

When the frontend receives HTTP 403 `account_disabled` from the OAuth callback with `appeal_enabled=true`, the application SHALL render a Lock card variant ("disabled state") containing: (a) the 🚫 icon, (b) the message "你的帳號目前無法使用，如果這是誤判可以提出申訴", (c) a primary button labeled "提出申訴" that opens the `AppealModal`. If `appeal_enabled=false`, the same Lock card SHALL render WITHOUT the appeal button and SHALL show only contact-admin guidance text.

#### Scenario: Disabled state with appeal enabled renders CTA

- **GIVEN** the OAuth callback returns HTTP 403 with body `{"error":"account_disabled","appeal_enabled":true}`
- **WHEN** the application processes the callback response
- **THEN** the Lock card SHALL render with the 🚫 icon, the disabled message, and the "提出申訴" button visible

#### Scenario: Disabled state with appeal disabled hides CTA

- **GIVEN** the callback returns `{"error":"account_disabled","appeal_enabled":false}`
- **WHEN** the application processes the response
- **THEN** the Lock card SHALL render with the 🚫 icon and disabled message
- **AND** the "提出申訴" button SHALL NOT be present

### Requirement: AppealModal collects reason and submits to backend

When the user clicks "提出申訴" in the disabled-state Lock card, the application SHALL open an `AppealModal` containing: (a) a read-only display of the email returned by the OAuth callback, (b) a textarea for the appeal reason (placeholder "請簡述為什麼你認為這是誤判", maxLength 2000, required), (c) a Submit button and a Cancel button. On Submit, the modal SHALL POST to `/auth/appeal` with `{ email, reason }`. On HTTP 200, the modal SHALL show "已收到你的申訴，管理員會在 1-2 個工作天內回覆" and replace the form with this confirmation. On HTTP 400 `invalid_reason`, the modal SHALL show an inline validation error. On HTTP 429 `rate_limited`, the modal SHALL show "今天的申訴次數已達上限，請明天再試".

#### Scenario: Successful submission shows confirmation

- **GIVEN** the AppealModal is open with a non-empty reason entered
- **WHEN** the user clicks Submit and the backend returns HTTP 200 `{"accepted":true,"appeal_id":"..."}`
- **THEN** the modal SHALL replace the form with the success confirmation text
- **AND** the Submit button SHALL NOT be visible

#### Scenario: Rate-limited submission shows guidance

- **WHEN** the user submits and the backend returns HTTP 429 `rate_limited`
- **THEN** the modal SHALL display the "今天的申訴次數已達上限" message
- **AND** the form SHALL remain editable for the user to retry tomorrow
