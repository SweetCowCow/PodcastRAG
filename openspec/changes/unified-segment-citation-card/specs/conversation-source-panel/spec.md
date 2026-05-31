## MODIFIED Requirements

### Requirement: Chat tab renders a single episode-grouped source panel

The Chat tab of `QueryPage` SHALL render answer citations in exactly one source panel below the AI answer. The panel SHALL replace the prior dual-region layout that combined a chip strip with a separate SourceCard list. Citations SHALL be grouped by `episode_id`; each episode group SHALL be a single visual block containing the episode title once at the top, followed by the chunks from that episode rendered as `SegmentCitationCard` items (the shared component defined by the `segment-citation-card` capability). Each episode group SHALL be collapsible by clicking the episode title. Within each episode group, at most the shared display cap of cards SHALL render initially, with a "顯示更多 / Show more" affordance to reveal the rest; the panel SHALL display only the chunks actually cited by the answer.

#### Scenario: Citations grouped by episode

- **GIVEN** an answer with citations C1(ep=A), C2(ep=B), C3(ep=A), C4(ep=A)
- **WHEN** the source panel renders
- **THEN** the panel SHALL contain exactly two episode groups: A (containing C1, C3, C4) and B (containing C2)
- **AND** the episode A group SHALL display the episode title exactly once
- **AND** there SHALL NOT be a separate chip strip duplicating the episode list

#### Scenario: Clicking episode title collapses the group

- **GIVEN** an expanded episode group containing two `SegmentCitationCard` items
- **WHEN** the user clicks the episode title
- **THEN** the cards in that group SHALL be hidden
- **AND** the episode title SHALL remain visible with an indicator that it can be re-expanded

#### Scenario: Each citation card exposes play and jump actions

- **GIVEN** an episode group containing a cited chunk with a playable `audio_url`
- **WHEN** its `SegmentCitationCard` renders
- **THEN** the card SHALL expose a "播放此段" button that plays without navigating AND a "跳到逐字稿" button that navigates to the transcript at the chunk's `start_time`
