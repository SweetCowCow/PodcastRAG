## ADDED Requirements

### Requirement: ChatBubble renders enumeration-driven main+collapse layout

The frontend `ChatBubble` component in `src/QueryPage.jsx` SHALL render chat responses with a layout that depends on whether the backend response contains a non-empty `enumeration_episodes` array:

1. **Enumeration layout** (when `enumeration_episodes` is a non-empty array): the bubble SHALL render `<EnumerationSection>` as the primary source visualization above the answer body, AND SHALL render the chunk-level `citations` inside a collapsible container `<CitationEvidenceCollapse>` BELOW the EnumerationSection. The collapsible container SHALL default to collapsed, with a summary label reading `為什麼這幾集被選 (N 個段落)` (where N is `citations.length`) in zh mode, or `Why these episodes (N excerpts)` in en mode. Expanding the container SHALL reveal the existing citation chip list and SourceCard rendering unchanged.

2. **Content layout** (when `enumeration_episodes` is null OR an empty array): the bubble SHALL render the existing chunk citation chips inline below the answer body, with NO collapsible container, NO EnumerationSection. This layout SHALL remain visually and behaviourally identical to the pre-change rendering.

The decision SHALL be made client-side based on `enumeration_episodes?.length > 0`. The backend response schema SHALL NOT change. Both layouts SHALL preserve existing `citation_click` event emission for analytics (the event SHALL fire when a chip is clicked, regardless of whether the surrounding container was collapsed or expanded when the user opened it).

#### Scenario: Enumeration query renders EnumerationSection above collapsed citations

- **GIVEN** the backend returns `{answer: "...", enumeration_episodes: [{id: 143, title: "EP143"}, {id: 82, title: "EP82"}], citations: [{episode_id: 143, start_time: 0}, {episode_id: 82, start_time: 120}]}`
- **WHEN** the ChatBubble renders this message
- **THEN** the EnumerationSection SHALL appear above the answer text
- **AND** below the answer text a single collapsed `<details>` block SHALL appear with summary text `為什麼這幾集被選 (2 個段落)`
- **AND** the citation chips SHALL NOT be visible until the user expands the `<details>` block

#### Scenario: Content query renders citation chips inline (no enumeration, no collapse)

- **GIVEN** the backend returns `{answer: "...", enumeration_episodes: null, citations: [{episode_id: 143, start_time: 1200}]}`
- **WHEN** the ChatBubble renders this message
- **THEN** the EnumerationSection SHALL NOT appear
- **AND** the citation chip SHALL render inline below the answer text (no `<details>` wrapper)
- **AND** the visual layout SHALL match the pre-change behaviour exactly

#### Scenario: Empty enumeration_episodes treated as content layout

- **GIVEN** the backend returns `{answer: "...", enumeration_episodes: [], citations: [{episode_id: 143, start_time: 0}]}`
- **WHEN** the ChatBubble renders this message
- **THEN** the rendering SHALL follow the content layout (no EnumerationSection, no collapse), because `enumeration_episodes.length === 0` evaluates to false

#### Scenario: citation_click event fires when chip clicked from expanded container

- **GIVEN** an enumeration-layout bubble whose `<CitationEvidenceCollapse>` has been expanded by the user
- **WHEN** the user clicks one of the now-visible citation chips
- **THEN** a `citation_click` event SHALL be sent to the backend `POST /events` endpoint with `chunk_id` populated as `ep:<episode_id>@<start_time>`
- **AND** the chip click SHALL trigger `onOpenEpisode(...)` navigation as before

#### Scenario: citation_click event fires identically in content layout

- **GIVEN** a content-layout bubble
- **WHEN** the user clicks a citation chip
- **THEN** the same `citation_click` event SHALL be sent with the same `chunk_id` format
- **AND** the navigation behaviour SHALL be identical to the enumeration layout case
