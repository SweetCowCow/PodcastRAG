## MODIFIED Requirements

### Requirement: Landing Page lists collected shows with real data

The Landing Page SHALL include a section labelled `收錄節目` (`zh`) / `Collected Shows` (`en`) below the hero. This section SHALL render one card per show returned by `GET /shows` (a public endpoint already in service) by reusing the `<ShowCard>` component exported by `src/PodcastSelect.jsx`. Each card SHALL display: the show's cover image (falling back to a colored mic icon when `image_url` is missing), the show title, the show's language label, a description (clamped to 3 lines), the show's total episode count, the transcribed episode count (in green), a transcription progress bar (with percentage label, full-green at 100%), the RSS feed URL (monospace, truncated with ellipsis), and an `進入節目` (`zh`) / `Open Show` (`en`) link with a chevron icon. Clicking anywhere on the card SHALL navigate to the show's QueryPage. The grid SHALL use `repeat(auto-fill, minmax(320px, 1fr))` on desktop and 1 column on mobile.

#### Scenario: Show cards reflect real backend data

- **GIVEN** the backend returns 3 shows with episode counts 139, 252, 162
- **WHEN** Landing renders the cards
- **THEN** each card SHALL show its corresponding episode count and title
- **AND** the cards SHALL render in the order returned by `GET /shows`

#### Scenario: Card click navigates to show's QueryPage

- **WHEN** the visitor clicks anywhere on the second card
- **THEN** the application SHALL navigate to the QueryPage for that show

#### Scenario: Card displays transcription progress bar

- **GIVEN** a show with `episode_count=139` and `transcribed_count=64`
- **WHEN** the card renders
- **THEN** the progress bar SHALL display 46% width filled
- **AND** the percentage label SHALL show `46%`

#### Scenario: Fully transcribed show shows green completion

- **GIVEN** a show with `episode_count=162` and `transcribed_count=162`
- **WHEN** the card renders
- **THEN** the progress bar SHALL be 100% filled in green
- **AND** the percentage label SHALL show `100%` in green

### Requirement: Landing Page paywall band explains the freemium boundary and offers login

The Landing Page SHALL include a paywall band section near the bottom (after the show cards) containing: the icon `💎`, a title exactly `登入解鎖：30 次 AI 統整回答` (`zh`) or `Log in to unlock: 30 free AI summary answers` (`en`); a body line `瀏覽逐字稿、看相關段落都不用登入。只有「請 AI 統整回答」需要登入使用額度。` (`zh`) / `Browsing transcripts and matched segments needs no login. Only "Ask AI to summarize" requires login and uses your quota.` (`en`); and a primary button `以 Google 登入 →` (`zh`) / `Sign in with Google →` (`en`). Clicking the button SHALL trigger the existing `LoginModal` component (from authentication-system).

#### Scenario: Paywall band is visible on Landing without scrolling past 2 viewport heights

- **GIVEN** a desktop viewport of 1024×768
- **WHEN** Landing renders
- **THEN** the paywall band SHALL be reachable within the first two viewport heights of scroll (i.e., user does not need to scroll more than ~1500 px to encounter it)

#### Scenario: Paywall login button opens the LoginModal

- **WHEN** the visitor clicks 以 Google 登入 →
- **THEN** the existing `LoginModal` SHALL open

#### Scenario: Paywall title omits one-time quota parenthetical

- **WHEN** Landing renders the paywall in `zh`
- **THEN** the displayed title SHALL be exactly `登入解鎖：30 次 AI 統整回答` (no parenthetical clause about one-time quota)

#### Scenario: Paywall body refers to login-and-quota requirement

- **WHEN** Landing renders the paywall in `zh`
- **THEN** the body text SHALL contain the substring `需要登入使用額度`
- **AND** the body text SHALL NOT contain the substring `會用到 quota`
