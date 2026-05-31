# semantic-mode-result-ui Specification

## Purpose

TBD - created by archiving change 'landing-and-mode-orchestration-redesign'. Update Purpose after archive.

## Requirements

### Requirement: Semantic results render as flat top-K list with same-episode collapse

The Semantic tab of `QueryPage` SHALL render retrieval results returned by the existing semantic search endpoint as a single flat list in the order returned (already RRF-ranked by the backend). When multiple chunks in the result list belong to the same episode, only the highest-ranked chunk for that episode SHALL render its full `SegmentCitationCard` (the shared component defined by the `segment-citation-card` capability); remaining same-episode chunks SHALL be collapsed into a single chip labelled `+{N} 同集` (`zh`) / `+{N} same episode` (`en`) attached to the kept card, where N is the number of collapsed chunks. Clicking the chip SHALL expand and render the collapsed chunks as additional `SegmentCitationCard` items immediately below the kept card.

#### Scenario: Two same-episode chunks collapse into one chip

- **GIVEN** the semantic endpoint returns chunks [C1(ep=A, rank=1), C2(ep=B, rank=2), C3(ep=A, rank=3)]
- **WHEN** the Semantic tab renders the results
- **THEN** the rendered list SHALL contain a `SegmentCitationCard` for C1 with a `+1 同集` chip, then a `SegmentCitationCard` for C2
- **AND** C3 SHALL NOT render its own card until the user clicks the chip

#### Scenario: Clicking the chip expands collapsed chunks

- **GIVEN** a `SegmentCitationCard` with a `+2 同集` chip
- **WHEN** the user clicks the chip
- **THEN** two additional `SegmentCitationCard` items SHALL render immediately below the kept card in their original ranked order
- **AND** the chip SHALL no longer be displayed (or SHALL change to a "collapse" affordance)

#### Scenario: Single chunk per episode renders no chip

- **GIVEN** the semantic endpoint returns chunks all from distinct episodes
- **WHEN** the Semantic tab renders the results
- **THEN** no `+N 同集` chip SHALL appear on any card


<!-- @trace
source: unified-segment-citation-card
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: Each Semantic SourceCard shows a relevance bar without raw score

Each `SegmentCitationCard` rendered in the Semantic tab SHALL display a visual relevance bar on the right side of the card, supplied via an optional relevance prop. The bar's fill width SHALL be a normalization of the backend-provided RRF score across the displayed result set: the top-ranked result SHALL fill 100% width and the bottom-ranked SHALL fill at least 10% width, with intermediate cards interpolated linearly. The numeric RRF score SHALL NOT be rendered as text anywhere on the card.

#### Scenario: Top result fills bar to 100 percent

- **GIVEN** a result set where C1 is rank 1 of 5
- **WHEN** the card for C1 renders
- **THEN** the relevance bar SHALL display 100% fill width

#### Scenario: Numeric RRF score is not visible to the user

- **WHEN** any Semantic card renders
- **THEN** no text matching a floating-point or RRF score pattern SHALL appear on the card

<!-- @trace
source: unified-segment-citation-card
updated: 2026-05-31
code:
  - skills-lock.json
-->

---
### Requirement: Semantic results over-fetch with a display cap and incremental show-more

The Semantic tab SHALL request `k = 25` from the public search endpoint (a single over-fetch; the endpoint already accepts `k` in the range 1–50). `SemanticResultList` SHALL apply a presentation cap to the per-episode groups it renders: it SHALL render at most 10 episode-groups initially, and when more than 10 groups are available it SHALL offer a "顯示更多 / Show more" affordance that reveals 5 additional groups per activation. Revealing more groups SHALL be a client-side slice of the already-fetched results and SHALL NOT issue a new search request. When all available groups are shown, the affordance SHALL NOT render. The result ordering and the existing same-episode collapse behavior SHALL be unchanged — this requirement governs display depth only, not retrieval ranking.

#### Scenario: More than ten groups shows the cap plus show-more

- **GIVEN** a semantic search whose results form 14 episode-groups after grouping
- **WHEN** the Semantic tab first renders the results
- **THEN** it SHALL render at most 10 episode-groups AND a "顯示更多 / Show more" affordance

#### Scenario: Show-more reveals five more groups without a new request

- **GIVEN** a rendered result set showing 10 of 14 groups with a "顯示更多" affordance
- **WHEN** the user activates "顯示更多"
- **THEN** 5 additional groups SHALL render (15 requested, 14 available → all 14 shown) without issuing a new search request
- **AND** once all 14 groups are shown the affordance SHALL NOT render

#### Scenario: Ten or fewer groups shows no show-more

- **GIVEN** a semantic search whose results form 6 episode-groups
- **WHEN** the Semantic tab renders the results
- **THEN** all 6 groups SHALL render AND no "顯示更多" affordance SHALL appear

#### Scenario: Search request carries k equal to 25

- **WHEN** the Semantic tab issues a search for a question
- **THEN** the request body to the public search endpoint SHALL include `k` equal to 25

<!-- @trace
source: semantic-topk-bump-and-show-more
updated: 2026-05-31
code:
  - skills-lock.json
-->