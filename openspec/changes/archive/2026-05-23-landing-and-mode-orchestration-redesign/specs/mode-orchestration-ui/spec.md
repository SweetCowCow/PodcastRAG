## ADDED Requirements

### Requirement: QueryPage exposes three mode tabs

The `QueryPage` SHALL render a tab strip at the top of the content area with exactly three tabs in this order: 索引 (`zh`) / Index (`en`), 語意 (`zh`) / Semantic (`en`), 對話 (`zh`) / Chat (`en`). Only one tab SHALL be active at a time. The tab labels and order SHALL NOT change based on auth state.

#### Scenario: Three tabs render in fixed order

- **WHEN** `QueryPage` mounts for any show
- **THEN** the tab strip SHALL contain three tabs in the order Index, Semantic, Chat

#### Scenario: Tab order is identical for authenticated and unauthenticated users

- **GIVEN** an unauthenticated visitor and an authenticated user opening the same show
- **WHEN** both QueryPages render
- **THEN** the visible tab strip SHALL have the same labels in the same order

### Requirement: Default tab is decided by authentication state

The active tab on initial QueryPage mount SHALL be Chat when `/me` resolves to an authenticated user. When the visitor is unauthenticated the active tab SHALL be Index. The decision SHALL be made once on mount after `/me` resolves; subsequent auth state changes SHALL NOT auto-switch the active tab.

#### Scenario: Unauthenticated visitor lands on Index tab

- **GIVEN** an unauthenticated visitor opens a show's QueryPage
- **WHEN** `/me` resolves with no user
- **THEN** the Index tab SHALL be the active tab

#### Scenario: Authenticated user lands on Chat tab

- **GIVEN** an authenticated user opens a show's QueryPage
- **WHEN** `/me` resolves with a user
- **THEN** the Chat tab SHALL be the active tab

#### Scenario: Logging in mid-session does not auto-switch active tab

- **GIVEN** an unauthenticated visitor is currently viewing the Semantic tab
- **WHEN** the visitor completes login successfully
- **THEN** the active tab SHALL remain Semantic

### Requirement: Switching tabs preserves input string and per-mode results

The QueryPage SHALL maintain a single controlled input value shared across all three tabs; switching tabs SHALL NOT clear the input. The QueryPage SHALL maintain independent result state buckets per mode; switching from a tab with displayed results to another tab and back SHALL restore the previously displayed results without re-fetching.

#### Scenario: Input string persists across tab switches

- **GIVEN** the user types `歌單` while on the Semantic tab
- **WHEN** the user switches to the Chat tab
- **THEN** the input field SHALL contain `歌單`

#### Scenario: Mode result buckets are independent

- **GIVEN** the user has executed a Semantic search returning results R_s, then switched to Chat and executed a chat returning result R_c
- **WHEN** the user switches back to Semantic
- **THEN** the Semantic results R_s SHALL be displayed without a new network request
- **AND** switching back to Chat SHALL display R_c without a new network request

### Requirement: Index tab renders placeholder pending backend implementation

The Index tab SHALL render a placeholder panel stating that the index mode is coming soon and suggesting the visitor try the Semantic or Chat tab. The Index tab SHALL NOT call any retrieval endpoint and SHALL NOT emit a `search_executed` event. The placeholder SHALL be replaced by real retrieval UI in a separate later change.

#### Scenario: Index tab shows placeholder without calling backend

- **WHEN** the user activates the Index tab and types a query
- **THEN** no retrieval HTTP request SHALL be issued
- **AND** the displayed content SHALL be the coming-soon placeholder

#### Scenario: Index tab placeholder offers route to Semantic and Chat

- **WHEN** the Index tab placeholder renders
- **THEN** the placeholder SHALL contain at least one element that switches to the Semantic tab and at least one that switches to the Chat tab
