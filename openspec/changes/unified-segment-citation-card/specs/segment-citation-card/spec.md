## ADDED Requirements

### Requirement: Unified segment citation card across modes

The frontend SHALL provide a single shared component `SegmentCitationCard` that renders one transcript-segment citation, and the Index, Semantic, and Chat modes SHALL render every per-segment citation through this component. The card SHALL display the matched transcript segment text, the episode title, and the segment start timestamp. The existing `SourceCard` SHALL either become this component or delegate to it so that prior callers continue to function.

#### Scenario: All three modes render the same card component

- **WHEN** a transcript-segment citation is shown in the Index tab (T1/T3), the Semantic tab, or the Chat tab source panel
- **THEN** it SHALL be rendered by `SegmentCitationCard`, showing the segment text, episode title, and start timestamp

#### Scenario: Description-source citation hides segment-only affordances

- **GIVEN** a citation whose `source` is `description` (no meaningful `start_time`)
- **WHEN** the card renders
- **THEN** the play button SHALL NOT render and the navigation button SHALL be labelled "打開該集" (`zh`) / "Open episode" (`en`) instead of a jump-to-timestamp label

### Requirement: Dual-mode term highlighting

`SegmentCitationCard` SHALL choose its highlight strategy by input precedence: (1) when a non-empty `terms` array is supplied, it SHALL highlight each term occurrence in the segment text with a deterministic two-color rotation by term order — even index orange (`#f97316`) with a solid underline, odd index cyan (`#06b6d4`) with a dashed underline; (2) otherwise when a server-rendered `highlights` HTML string is supplied, it SHALL render that HTML after passing it through the existing `sanitiseMarkOnly` sanitiser, with a single accent-color `<mark>` style; (3) otherwise it SHALL render the plain segment text.

#### Scenario: Multi-term query uses two-color highlight

- **GIVEN** `terms = ["A", "B", "C"]` supplied to the card
- **WHEN** the segment text contains all three terms
- **THEN** "A" SHALL render orange with a solid underline, "B" cyan with a dashed underline, and "C" orange with a solid underline

#### Scenario: Server highlights use single-color sanitised rendering

- **GIVEN** no `terms` array but a server `highlights` HTML string containing `<mark>` wrappers
- **WHEN** the card renders
- **THEN** the HTML SHALL be sanitised via `sanitiseMarkOnly` and the matched spans SHALL render with the single accent-color highlight style

### Requirement: Separate play and jump-to-transcript actions

`SegmentCitationCard` SHALL expose two distinct actions instead of a single combined one: a "▶ 播放此段 / Play" button that invokes the `onPlay` callback (which the host wires to the existing sticky audio player at the segment `start_time`) WITHOUT navigating away from the current view, and a "跳到逐字稿 / Jump to transcript" button that invokes the `onJumpToTranscript` callback (which the host wires to navigate to the transcript view at the segment `start_time`). The play button SHALL be omitted when the segment has no playable `audio_url` or when no audio player is available.

#### Scenario: Play does not navigate

- **GIVEN** a card for a segment with a playable `audio_url`
- **WHEN** the user clicks "播放此段"
- **THEN** the sticky audio player SHALL start playback at the segment `start_time` AND the current results view SHALL remain displayed (no navigation)

#### Scenario: Jump navigates to the transcript at the segment

- **WHEN** the user clicks "跳到逐字稿" on a segment with `start_time = 145.3`
- **THEN** the host SHALL navigate to the transcript view positioned at 145.3 seconds

#### Scenario: No audio hides the play button

- **GIVEN** a segment whose `audio_url` is absent
- **WHEN** the card renders
- **THEN** the play button SHALL NOT render and the jump-to-transcript button SHALL still render

### Requirement: Displayed citation count decoupled from retrieval top_k

The number of citation cards displayed SHALL be governed by a presentation cap, not by the retrieval `top_k`. Each section (Index T1/T3) or per-episode group (Semantic, Chat) SHALL render at most a fixed display cap of cards initially and SHALL offer a "顯示更多 / Show more" affordance to reveal additional cards incrementally. Chat answers SHALL display only the chunks actually cited by the answer (`cited_hits`), not every retrieved chunk.

#### Scenario: Group over the cap shows a "show more" affordance

- **GIVEN** a per-episode group or section containing more cards than the display cap
- **WHEN** it first renders
- **THEN** it SHALL render at most the cap number of cards AND a "顯示更多" affordance
- **WHEN** the user activates "顯示更多"
- **THEN** additional cards SHALL appear incrementally without a full page reload

#### Scenario: Chat shows only cited chunks

- **GIVEN** a chat answer whose retrieval returned more chunks than the answer cited
- **WHEN** the source panel renders
- **THEN** it SHALL display only the cited chunks, and the displayed count SHALL NOT increase merely because `top_k` was larger

### Requirement: Enumeration episodes expand to inline segment cards

When a list-style container presents an episode list (the Chat enumeration result), it SHALL keep the episode list as its primary structure, and each episode entry SHALL offer an inline "展開查看各段 / View segments" expansion that renders that episode's matching segments as `SegmentCitationCard` items in place, without navigating away.

#### Scenario: Expanding an enumeration episode shows segment cards inline

- **GIVEN** a Chat enumeration result listing episodes
- **WHEN** the user expands one episode entry
- **THEN** that episode's matching segments SHALL render as `SegmentCitationCard` items directly beneath the entry AND the page SHALL NOT navigate away

#### Scenario: Enumeration episode with no matching segments

- **GIVEN** an enumeration episode whose segment fetch returns no term-matching segments
- **WHEN** the user expands it
- **THEN** a "（此集無可顯示的命中段落）" (`zh`) / "(no matching segments to show)" (`en`) placeholder SHALL render in place, without an error
