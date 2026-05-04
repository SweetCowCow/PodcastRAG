## ADDED Requirements

### Requirement: Landing Page renders for unauthenticated visitors at site root

The frontend application SHALL render a `LandingPage` React component at the route `/` when the visitor is unauthenticated. When the visitor is authenticated (a valid `session_id` cookie resolves to a user via `/me`), the application SHALL render the `PodcastSelect` component instead at `/`. The decision SHALL be made client-side after the initial `/me` fetch resolves; before resolution the application SHALL render a neutral loading state (no flash of LandingPage to authenticated users on hard refresh).

#### Scenario: First-time visitor sees Landing

- **GIVEN** a browser with no `session_id` cookie
- **WHEN** the visitor navigates to `/`
- **THEN** the LandingPage component SHALL be rendered

#### Scenario: Returning logged-in user skips Landing

- **GIVEN** a browser whose `session_id` cookie resolves to an active user
- **WHEN** the visitor navigates to `/`
- **THEN** PodcastSelect SHALL be rendered, not LandingPage

#### Scenario: Hard refresh on Landing while logged in does not flash Landing

- **GIVEN** a logged-in user on `/`
- **WHEN** the user hits browser refresh
- **THEN** the application SHALL show a loading indicator until `/me` resolves
- **AND** SHALL render PodcastSelect once `/me` confirms authentication
- **AND** SHALL NOT render LandingPage at any point during this transition

### Requirement: Landing Page hero presents copy and primary CTA

The Landing Page hero section SHALL contain (top to bottom):

1. An H1 with text exactly: 「那個來賓說過什麼？」別再瘋狂快轉了。 (`zh`) / "What did that guest say?" Stop fast-forwarding through podcasts. (`en`)
2. An H2 / subtitle with text: 忘記在哪一集沒關係。直接問，從節目片段中找回那道遺忘的靈光一閃，瞬間解開你的疑惑。(`zh`) / Forgotten which episode it was in? Just ask. Find the moment of insight you remember, instantly. (`en`)
3. A primary text input (search box) with placeholder exactly: 例如：在 這又沒有很屌 查詢「歌單」 (`zh`) / Example: search "playlist" in 這又沒有很屌 (`en`)
4. A primary CTA button labelled 找回靈光一閃 (`zh`) / Bring back the insight (`en`) immediately to the right of (or below on mobile) the search input

When the visitor types into the search box and presses Enter or clicks the CTA, the application SHALL navigate to the multi-show search experience with the typed query pre-filled. The exact target route MAY be `/select?q=<query>` (auto-pick most-relevant show) or a dedicated cross-show search page; the choice belongs to the implementation but the user-facing behavior MUST be that the typed query is preserved.

#### Scenario: Empty search box and CTA click navigate to select page

- **WHEN** the visitor clicks the CTA without typing
- **THEN** the application SHALL navigate to the show-selection experience
- **AND** the page MAY focus the search input or show a hint, but SHALL NOT show an error

#### Scenario: Typed query is preserved across navigation

- **WHEN** the visitor types `歌單` and presses Enter
- **THEN** the destination page SHALL receive `歌單` as the active query (URL param, store state, or equivalent)

#### Scenario: Bilingual copy switches with language toggle

- **GIVEN** the language toggle is set to `en`
- **WHEN** Landing renders
- **THEN** all four hero strings SHALL appear in their English forms exactly as specified above

### Requirement: Landing Page lists collected shows with real data

The Landing Page SHALL include a section labelled `收錄節目` (`zh`) / `Collected Shows` (`en`) below the hero. This section SHALL render one card per show returned by `GET /shows` (a public endpoint already in service). Each card SHALL display: show title, a one-line description (truncated from `Show.description`, max 60 zh chars / 100 en chars), the show's total episode count, the show's transcribed episode count or completion ratio, and a button labelled `瀏覽集數 →` (`zh`) / `Browse episodes →` (`en`) that navigates to the show's QueryPage. The grid SHALL use 3 columns on desktop (`window.innerWidth >= 768`) and 1 column on mobile.

#### Scenario: Show cards reflect real backend data

- **GIVEN** the backend returns 3 shows with episode counts 139, 252, 162
- **WHEN** Landing renders the cards
- **THEN** each card SHALL show its corresponding episode count and title
- **AND** the cards SHALL render in the order returned by `GET /shows`

#### Scenario: Card click navigates to show's QueryPage

- **WHEN** the visitor clicks the `瀏覽集數 →` button on the second card
- **THEN** the application SHALL navigate to the QueryPage for that show

#### Scenario: Long description is truncated

- **GIVEN** a show with a 500-character description
- **WHEN** Landing renders the card
- **THEN** the displayed description SHALL be at most 60 zh chars (truncated with `…`) or 100 en chars depending on language

### Requirement: Landing Page paywall band explains the freemium boundary and offers login

The Landing Page SHALL include a paywall band section near the bottom (after the show cards) containing: the icon `💎`, a title exactly `登入解鎖：30 次 AI 統整回答（一次性免費額度，用完可申請補充）` (`zh`) or `Log in to unlock: 30 free AI summary answers (one-time, request more once depleted)` (`en`); a body line `瀏覽逐字稿、看相關段落都不用登入。只有「請 AI 統整回答」會用到 quota。` (`zh`) / `Browsing transcripts and seeing matched segments stays free. Only AI-generated summaries use your quota.` (`en`); and a primary button `以 Google 登入 →` (`zh`) / `Sign in with Google →` (`en`). Clicking the button SHALL trigger the existing `LoginModal` component (from authentication-system).

#### Scenario: Paywall band is visible on Landing without scrolling past 2 viewport heights

- **GIVEN** a desktop viewport of 1024×768
- **WHEN** Landing renders
- **THEN** the paywall band SHALL be reachable within the first two viewport heights of scroll (i.e., user does not need to scroll more than ~1500 px to encounter it)

#### Scenario: Paywall login button opens the LoginModal

- **WHEN** the visitor clicks 以 Google 登入 →
- **THEN** the existing `LoginModal` SHALL open
- **AND** the modal's success callback SHALL navigate the user to PodcastSelect (post-login default destination)

### Requirement: Landing Page top navigation includes secondary login button

The Landing Page top navigation bar SHALL display, in addition to the language toggle, a secondary `登入` (`zh`) / `Log in` (`en`) button on the right side. Clicking this button SHALL open the same `LoginModal` as the paywall band. This button SHALL be visually subordinate to the hero CTA (smaller, ghost / outline style) so the primary visual emphasis remains on the search hero.

#### Scenario: Top nav login button opens LoginModal

- **WHEN** the visitor clicks the top-right `登入` button
- **THEN** the `LoginModal` SHALL open
