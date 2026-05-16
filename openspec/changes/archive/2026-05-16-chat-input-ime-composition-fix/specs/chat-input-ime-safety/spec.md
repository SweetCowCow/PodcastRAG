## ADDED Requirements

### Requirement: Enter-to-submit MUST honor IME composition state

The shared `<Input>` component SHALL accept an optional `onSubmit` callback prop. When the user presses Enter inside the underlying `<input>` element, the component SHALL invoke `onSubmit` ONLY IF the browser reports that no IME composition is active (`event.isComposing === false` AND `event.keyCode !== 229`). When a composition is active (i.e. the user is selecting a candidate character from a CJK input method such as 注音 / 倉頡 / 拼音), the Enter keystroke SHALL be consumed by the IME for candidate confirmation and SHALL NOT trigger `onSubmit`. Any caller-supplied `onKeyDown` prop SHALL still fire after the guard logic so existing key listeners keep working.

#### Scenario: Bopomofo candidate-confirm Enter does NOT submit

- **GIVEN** the chat input is focused and the user has typed Bopomofo phonetic input that has surfaced a candidate-character window
- **WHEN** the user presses Enter to confirm the candidate
- **THEN** `onSubmit` SHALL NOT be invoked
- **AND** the candidate character SHALL be inserted into the input value as the IME would normally do

#### Scenario: Plain Enter (no IME composition) DOES submit

- **GIVEN** the chat input is focused, the value is the non-empty string "節目名怎麼來的", and no IME composition is active
- **WHEN** the user presses Enter
- **THEN** `onSubmit` SHALL be invoked exactly once with the keyboard event

#### Scenario: Empty-value Enter is no-op at component level

- **GIVEN** the chat input is focused, the value is the empty string, and no IME composition is active
- **WHEN** the user presses Enter
- **THEN** `onSubmit` SHALL be invoked (the component does NOT gate on value emptiness — the caller's `onSubmit` handler MAY choose to no-op when the trimmed value is empty, mirroring the existing `handleSend` / `handleSearch` guards)

#### Scenario: Caller-supplied onKeyDown still fires

- **GIVEN** the input is rendered with both `onSubmit={fnA}` and `onKeyDown={fnB}`
- **WHEN** the user presses Enter while no IME composition is active
- **THEN** `fnA` SHALL be invoked AND `fnB` SHALL ALSO be invoked, in that order

#### Scenario: Legacy keyCode 229 path is treated as composition

- **GIVEN** the browser is Safari or iOS WebKit which sometimes reports `event.keyCode === 229` while `event.isComposing === false` during IME composition
- **WHEN** the user presses Enter in this state
- **THEN** the component SHALL treat the keystroke as composition and SHALL NOT invoke `onSubmit`

### Requirement: QueryPage chat + semantic-search inputs MUST use the IME-safe submit path

`src/QueryPage.jsx` SHALL wire its chat-bubble input and its semantic-search input to the `<Input>` component's `onSubmit` prop (NOT a raw `onKeyDown={e => e.key === 'Enter' && handler()}` listener). The two on-page handlers `handleSend` and `handleSearch` SHALL be passed as `onSubmit` so the IME guard in the shared component applies uniformly.

#### Scenario: Chat input uses onSubmit prop

- **WHEN** the QueryPage chat input is rendered
- **THEN** it SHALL be passed `onSubmit={handleSend}` (not `onKeyDown`-based Enter detection)

#### Scenario: Semantic search input uses onSubmit prop

- **WHEN** the QueryPage semantic-search input is rendered
- **THEN** it SHALL be passed `onSubmit={handleSearch}` (not `onKeyDown`-based Enter detection)
