## REMOVED Requirements

### Requirement: Landing Page renders for unauthenticated visitors at site root

**Reason**: Replaced by the new `home-page` capability. The route `/` is now served by a single `HomePage` component for both authenticated and unauthenticated visitors, removing the prior split between `LandingPage` and `PodcastSelect`.

**Migration**: Implementers SHALL delete `src/LandingPage.jsx` and `src/PodcastSelect.jsx` and route `/` to `src/HomePage.jsx`. The auth-aware hero swap that was previously expressed by selecting between two components is now expressed by `HomePage`'s internal hero variant logic (see capability `home-page`).

### Requirement: Landing Page hero presents copy and primary CTA

**Reason**: The Landing hero text and the cross-show search input pattern are superseded by `HomePage`'s auth-state-dependent hero variants and the new mode trio education section. The cross-show search input is replaced by the per-show flow: visitors pick a show card first, then choose Index, Semantic, or Chat mode on QueryPage.

**Migration**: Implementers SHALL remove the hero `<input>` + CTA from any surviving landing markup and SHALL rely on the show-grid-then-QueryPage flow for query entry. The bilingual hero copy SHALL be replaced by the variants defined under capability `home-page`.

### Requirement: Landing Page lists collected shows with real data

**Reason**: The show grid behavior moves into `home-page` capability unchanged in semantics (same data source, same card structure, same click behavior). Keeping the requirement under `landing-page` would duplicate it.

**Migration**: Implementers SHALL implement the show grid under `HomePage` per the `home-page` capability requirement "HomePage renders show grid with real backend data".

### Requirement: Landing Page paywall band explains the freemium boundary and offers login

**Reason**: The paywall band on Landing is replaced by two surfaces: (a) the unauthenticated hero variant in `HomePage` which contains the Google login CTA, and (b) the new `LockCard` (variant `anonymous`) which covers the Chat tab answer area and explains the login requirement at the point of need. The specific copy `登入解鎖：30 次 AI 統整回答` and `會用到 quota` is retired; replacement copy is defined in capability `lock-card-ui` and explicitly avoids quota number and reset wording on the marketing surface.

**Migration**: Implementers SHALL remove the paywall band from the homepage flow. Login entry SHALL remain available through (a) the hero CTA in `HomePage` for unauthenticated visitors and (b) the existing top navigation login button, both of which continue to open `LoginModal`.

### Requirement: Landing Page top navigation includes secondary login button

**Reason**: The TopNav login button is owned by the global `App.jsx` navigation chrome and is not specific to the Landing surface. With Landing being replaced by `HomePage`, the requirement is more accurately captured by the auth-system capability (which already governs `LoginModal` triggers) and by `home-page`'s hero CTA.

**Migration**: Implementers SHALL keep the existing TopNav login button behavior (no functional change) but SHALL stop attributing it to the `landing-page` capability. No code change is required for the TopNav login button itself.
