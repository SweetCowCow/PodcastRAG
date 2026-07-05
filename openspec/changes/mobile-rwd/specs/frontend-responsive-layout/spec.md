## ADDED Requirements

### Requirement: Button labels never wrap into vertical text

The shared `Btn` component in src/Shared.jsx SHALL set `whiteSpace: 'nowrap'` in its base style so that button label text renders on a single line at every viewport width. When a flex container is too narrow for a button's single-line label, the button SHALL keep its single-line label (the surrounding layout adapts, e.g. by wrapping the button to its own row or truncating sibling content); character-per-line vertical wrapping SHALL NOT occur. Individual call sites MAY override the base style only to shorten a label or re-layout the row, and SHALL NOT re-enable label wrapping.

#### Scenario: Send and search buttons stay single-line on mobile

- **GIVEN** a 375 px-wide mobile viewport on the QueryPage
- **WHEN** the 送出 (send) button in the chat tab and the 搜尋 (search) button in the keyword tab render
- **THEN** each button's label SHALL render on one line (label height equals one line-height, not stacked characters)

#### Scenario: Admin add-key button stays single-line on mobile

- **GIVEN** a 375 px-wide mobile viewport on the admin API-keys tab
- **WHEN** the 新增金鑰 (add key) button renders next to the description paragraph
- **THEN** the button label SHALL render on one line and the button SHALL NOT overflow the viewport

#### Scenario: English locale buttons do not overflow their container

- **GIVEN** a 375 px-wide mobile viewport with the interface language set to English
- **WHEN** the home, query, and first three admin tabs render
- **THEN** no `Btn` element SHALL overflow its parent container's visible bounds

### Requirement: Chat input dock collapses example chips once a conversation exists

On mobile (`isMobile === true`), the QueryPage chat tab's bottom input dock (example chips + input row + scope footnote) SHALL collapse the example-chips block whenever the conversation contains at least one message, and the collapsed dock's total height SHALL NOT exceed 25% of the viewport height. A visible affordance labelled 範例 (`zh`) / Examples (`en`) SHALL remain, and activating it SHALL re-expand the chips without clearing the conversation. On desktop (`isMobile === false`) the current always-expanded behavior SHALL remain unchanged.

#### Scenario: Chips collapse after first message on mobile

- **GIVEN** a 375×667 mobile viewport with an empty chat
- **WHEN** the user sends a first chat message
- **THEN** the example-chips block SHALL collapse and the bottom dock height SHALL be at most 25% of the viewport height

#### Scenario: Collapsed chips can be re-expanded

- **GIVEN** a mobile chat with at least one message and collapsed chips
- **WHEN** the user activates the 範例 / Examples affordance
- **THEN** the example chips SHALL be visible again and tapping a chip SHALL submit that example query as before

#### Scenario: Desktop dock unchanged

- **GIVEN** a 1280 px desktop viewport with an ongoing conversation
- **WHEN** the chat tab renders
- **THEN** the example chips SHALL render exactly as before this change (no collapse affordance required)

### Requirement: Admin tab bar keeps the active tab visible on mobile

On mobile, the admin page's horizontally scrollable tab bar SHALL automatically scroll the active tab into view: on initial mount using instant positioning, and on every subsequent tab change using `scrollIntoView` with horizontal `inline: 'nearest'` alignment. After any tab switch the active tab's full label SHALL be inside the tab bar's visible area.

#### Scenario: Late tab selected via navigation is visible

- **GIVEN** a 375 px mobile viewport on the admin page
- **WHEN** the user switches to a tab that sits beyond the initially visible tab-bar area (e.g., 服務用量 / provider usage)
- **THEN** the tab bar SHALL scroll so that the active tab's full label is visible without manual scrolling

#### Scenario: Initial mount shows active tab

- **GIVEN** the admin page loads with a non-first tab active (e.g., restored state)
- **WHEN** the tab bar mounts
- **THEN** the active tab SHALL already be inside the visible tab-bar area without animation artifacts
