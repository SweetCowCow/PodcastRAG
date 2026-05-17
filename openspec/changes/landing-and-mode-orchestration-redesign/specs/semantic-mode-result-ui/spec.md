## ADDED Requirements

### Requirement: Semantic results render as flat top-K list with same-episode collapse

The Semantic tab of `QueryPage` SHALL render retrieval results returned by the existing semantic search endpoint as a single flat list in the order returned (already RRF-ranked by the backend). When multiple chunks in the result list belong to the same episode, only the highest-ranked chunk for that episode SHALL render its full SourceCard; remaining same-episode chunks SHALL be collapsed into a single chip labelled `+{N} 同集` (`zh`) / `+{N} same episode` (`en`) attached to the kept SourceCard, where N is the number of collapsed chunks. Clicking the chip SHALL expand and render the collapsed chunks as additional SourceCards immediately below the kept card.

#### Scenario: Two same-episode chunks collapse into one chip

- **GIVEN** the semantic endpoint returns chunks [C1(ep=A, rank=1), C2(ep=B, rank=2), C3(ep=A, rank=3)]
- **WHEN** the Semantic tab renders the results
- **THEN** the rendered list SHALL contain a SourceCard for C1 with a `+1 同集` chip, then a SourceCard for C2
- **AND** C3 SHALL NOT render its own SourceCard until the user clicks the chip

#### Scenario: Clicking the chip expands collapsed chunks

- **GIVEN** a SourceCard with a `+2 同集` chip
- **WHEN** the user clicks the chip
- **THEN** two additional SourceCards SHALL render immediately below the kept card in their original ranked order
- **AND** the chip SHALL no longer be displayed (or SHALL change to a "collapse" affordance)

#### Scenario: Single chunk per episode renders no chip

- **GIVEN** the semantic endpoint returns chunks all from distinct episodes
- **WHEN** the Semantic tab renders the results
- **THEN** no `+N 同集` chip SHALL appear on any SourceCard

### Requirement: Each Semantic SourceCard shows a relevance bar without raw score

Each SourceCard rendered in the Semantic tab SHALL display a visual relevance bar on the right side of the card. The bar's fill width SHALL be a normalization of the backend-provided RRF score across the displayed result set: the top-ranked result SHALL fill 100% width and the bottom-ranked SHALL fill at least 10% width, with intermediate cards interpolated linearly. The numeric RRF score SHALL NOT be rendered as text anywhere on the card.

#### Scenario: Top result fills bar to 100 percent

- **GIVEN** a result set where C1 is rank 1 of 5
- **WHEN** the SourceCard for C1 renders
- **THEN** the relevance bar SHALL display 100% fill width

#### Scenario: Numeric RRF score is not visible to the user

- **WHEN** any Semantic SourceCard renders
- **THEN** no text matching a floating-point or RRF score pattern SHALL appear on the card
