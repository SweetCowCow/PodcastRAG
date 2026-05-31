## ADDED Requirements

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
