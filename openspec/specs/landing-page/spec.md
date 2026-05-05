# landing-page Specification

## Purpose

TBD - created by archiving change 'freemium-onboarding'. Update Purpose after archive.

## Requirements

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


<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->

---
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


<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->

---
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


<!-- @trace
source: r1-ui-feedback-infra
updated: 2026-05-05
code:
  - src/LandingPage.jsx
  - backend/alembic/versions/q5f6a7b8c9d0_add_qa_feedback_and_events.py
  - src/QueryPage.jsx
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/case-studies/zeabur-platform-case-study.md
  - docs/research/competitive-analysis.md
  - docs/case-studies/transcription-queue-discussion.md
  - aisteps-tab.png
  - backend/app/schemas/event.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/api/events.py
  - backend/app/api/qa_feedback.py
  - backend/app/main.py
  - backend/app/models/qa_feedback.py
  - backend/app/core/csrf.py
  - backend/app/schemas/query.py
  - backend/app/schemas/qa_feedback.py
  - docs/case-studies/build-zeabur-pptx.js
  - backend/app/api/query.py
  - src/PodcastSelect.jsx
  - docs/research/competitive-feature-plan.md
  - docs/research/r1-rag-eval-brief.md
  - backend/app/models/event.py
  - backend/app/core/rate_limit.py
  - index.html
  - backend/app/models/__init__.py
tests:
  - backend/tests/test_qa_feedback_api.py
  - backend/tests/test_qa_feedback_stats.py
  - backend/tests/test_events_api.py
-->

---
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


<!-- @trace
source: r1-ui-feedback-infra
updated: 2026-05-05
code:
  - src/LandingPage.jsx
  - backend/alembic/versions/q5f6a7b8c9d0_add_qa_feedback_and_events.py
  - src/QueryPage.jsx
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/case-studies/zeabur-platform-case-study.md
  - docs/research/competitive-analysis.md
  - docs/case-studies/transcription-queue-discussion.md
  - aisteps-tab.png
  - backend/app/schemas/event.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/api/events.py
  - backend/app/api/qa_feedback.py
  - backend/app/main.py
  - backend/app/models/qa_feedback.py
  - backend/app/core/csrf.py
  - backend/app/schemas/query.py
  - backend/app/schemas/qa_feedback.py
  - docs/case-studies/build-zeabur-pptx.js
  - backend/app/api/query.py
  - src/PodcastSelect.jsx
  - docs/research/competitive-feature-plan.md
  - docs/research/r1-rag-eval-brief.md
  - backend/app/models/event.py
  - backend/app/core/rate_limit.py
  - index.html
  - backend/app/models/__init__.py
tests:
  - backend/tests/test_qa_feedback_api.py
  - backend/tests/test_qa_feedback_stats.py
  - backend/tests/test_events_api.py
-->

---
### Requirement: Landing Page top navigation includes secondary login button

The Landing Page top navigation bar SHALL display, in addition to the language toggle, a secondary `登入` (`zh`) / `Log in` (`en`) button on the right side. Clicking this button SHALL open the same `LoginModal` as the paywall band. This button SHALL be visually subordinate to the hero CTA (smaller, ghost / outline style) so the primary visual emphasis remains on the search hero.

#### Scenario: Top nav login button opens LoginModal

- **WHEN** the visitor clicks the top-right `登入` button
- **THEN** the `LoginModal` SHALL open

<!-- @trace
source: freemium-onboarding
updated: 2026-05-04
code:
  - docs/research/competitive-analysis.md
  - backend/app/main.py
  - backend/app/models/user.py
  - backend/app/api/admin/__init__.py
  - backend/app/services/zsend.py
  - backend/app/services/user_service.py
  - backend/app/models/__init__.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - src/App.jsx
  - backend/app/core/config.py
  - src/AdminPage.jsx
  - src/QueryPage.jsx
  - backend/alembic/versions/p4e5f6a7b8c9_add_quota_requests.py
  - backend/app/schemas/errors.py
  - backend/app/api/query.py
  - src/QuotaMeter.jsx
  - backend/app/core/security.py
  - src/Shared.jsx
  - backend/.env.example
  - backend/app/models/quota_request.py
  - backend/app/workers/celery_app.py
  - docs/case-studies/transcription-queue-discussion.md
  - backend/app/core/rate_limit.py
  - src/QuotaApplyModal.jsx
  - backend/app/api/quota_requests.py
  - backend/app/api/admin/quota_requests.py
  - backend/app/schemas/query.py
  - backend/app/workers/quota_digest.py
  - src/QuotaRequestsTab.jsx
  - backend/app/core/csrf.py
  - backend/app/schemas/quota_request.py
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/research/competitive-feature-plan.md
  - aisteps-tab.png
  - src/LandingPage.jsx
  - index.html
tests:
  - backend/tests/test_public_search.py
  - backend/tests/test_quota_requests_admin.py
  - backend/tests/test_quota_requests_api.py
  - backend/tests/test_auth_db.py
  - backend/tests/test_ip_rate_limit.py
  - backend/tests/test_optional_auth.py
  - backend/tests/test_config.py
  - backend/tests/test_zsend_client.py
  - backend/tests/test_quota_digest_task.py
-->