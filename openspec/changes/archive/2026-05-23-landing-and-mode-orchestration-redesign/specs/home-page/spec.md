## ADDED Requirements

### Requirement: HomePage replaces LandingPage and PodcastSelect at site root

The frontend application SHALL render a single `HomePage` React component at the route `/` for both authenticated and unauthenticated visitors. `HomePage` SHALL replace the prior split between `LandingPage` (unauthenticated) and `PodcastSelect` (authenticated). The decision to swap hero content SHALL be made client-side after the initial `/me` fetch resolves; before resolution the application SHALL render a neutral loading state and SHALL NOT flash either hero variant.

#### Scenario: Unauthenticated visitor sees HomePage with marketing hero

- **GIVEN** a browser with no `session_id` cookie
- **WHEN** the visitor navigates to `/`
- **THEN** `HomePage` SHALL render with the marketing hero variant
- **AND** the show grid section SHALL also render below the hero

#### Scenario: Authenticated visitor sees HomePage with personalized hero

- **GIVEN** a browser whose `session_id` cookie resolves to an active user
- **WHEN** the visitor navigates to `/`
- **THEN** `HomePage` SHALL render with the authenticated hero variant containing the user's greeting and remaining quota
- **AND** the show grid section SHALL render below the hero

#### Scenario: Hard refresh while logged in does not flash marketing hero

- **GIVEN** a logged-in user on `/`
- **WHEN** the user hits browser refresh
- **THEN** the application SHALL show a loading indicator until `/me` resolves
- **AND** SHALL render the authenticated hero variant once `/me` confirms authentication
- **AND** SHALL NOT render the marketing hero variant at any point during this transition

### Requirement: HomePage shows mode trio education section

The `HomePage` SHALL include a section between the hero and the show grid containing three non-interactive cards labelled in order: 索引 (`zh`) / Index (`en`), 語意 (`zh`) / Semantic (`en`), 對話 (`zh`) / Chat (`en`). Each card SHALL display: the mode name, a one-sentence description of what kind of question it suits, exactly one fixed example query, and a quota label (the index and semantic cards SHALL state "no login required"; the chat card SHALL state the per-user 30-call quota in plain language without specifying reset semantics). The cards SHALL NOT be clickable (no cursor: pointer, no onClick handler). On viewports narrower than 768px the three cards SHALL stack vertically.

#### Scenario: Mode trio renders three non-clickable cards

- **WHEN** `HomePage` renders on a 1280px-wide viewport
- **THEN** three mode cards SHALL appear in a horizontal row in the order Index, Semantic, Chat
- **AND** no card SHALL respond to click events or display a pointer cursor on hover

#### Scenario: Mode trio stacks vertically on narrow viewports

- **GIVEN** a viewport width of 375px
- **WHEN** `HomePage` renders
- **THEN** the three mode cards SHALL stack vertically in a single column

### Requirement: HomePage renders show grid with real backend data

The `HomePage` SHALL include a section labelled 收錄節目 (`zh`) / Collected Shows (`en`) below the mode trio. This section SHALL render one card per show returned by `GET /shows` using a `<ShowCard>` component. Each card SHALL display: cover image (with fallback colored icon when `image_url` is missing), show title, language label, description clamped to 3 lines, total episode count, transcribed episode count, transcription progress bar with percentage, RSS feed URL, and an `進入節目` (`zh`) / `Open Show` (`en`) link. Clicking anywhere on a card SHALL navigate to the show's QueryPage. The grid SHALL use `repeat(auto-fill, minmax(320px, 1fr))` on desktop and 1 column on mobile.

#### Scenario: Show cards render in backend-returned order

- **GIVEN** `GET /shows` returns shows S1, S2, S3
- **WHEN** the show grid renders
- **THEN** the cards SHALL appear in the order S1, S2, S3

#### Scenario: Card click navigates to QueryPage for that show

- **WHEN** the visitor clicks anywhere on a show card
- **THEN** the application SHALL navigate to the QueryPage for that show

### Requirement: HomePage hero CTA differs by auth state

The `HomePage` hero SHALL render two variants. The unauthenticated variant SHALL contain a marketing headline, a subtitle, and a primary CTA labelled 以 Google 登入 (`zh`) / Sign in with Google (`en`) that opens the existing `LoginModal`. The authenticated variant SHALL contain a personalized greeting using the user's display name, the user's remaining chat quota count, and SHALL NOT contain a Google login CTA. Both variants SHALL share the same show grid and mode trio below the hero.

#### Scenario: Unauthenticated hero shows Google login CTA

- **WHEN** an unauthenticated visitor sees the hero
- **THEN** the hero SHALL contain a button that opens `LoginModal` on click

#### Scenario: Authenticated hero shows personalized greeting

- **GIVEN** an authenticated user named "Alice" with remaining chat quota of 17
- **WHEN** the hero renders
- **THEN** the hero SHALL contain the name "Alice" and the number "17"
- **AND** the hero SHALL NOT contain a Google login button
