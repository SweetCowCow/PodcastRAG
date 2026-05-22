# paragraph-aggregation Specification

## Purpose

TBD - created by archiving change 'landing-and-mode-orchestration-redesign'. Update Purpose after archive.

## Requirements

### Requirement: aggregateParagraphs util produces paragraphs by silence gap and speaker change

The frontend SHALL expose a pure function `aggregateParagraphs(segments, opts)` where `segments` is an array of objects each containing `text`, `start_time`, `end_time`, and `speaker` (and arbitrary other fields preserved on each `segment_ids` reference), and `opts` accepts `gap_threshold_seconds` (number, default 1.5). The function SHALL return an array of paragraph objects each containing `paragraph_text` (segments joined by single spaces), `start_time` (first segment's start), `end_time` (last segment's end), `speaker` (the shared speaker for that paragraph), and `segment_ids` (UUIDs of contained segments in order). A new paragraph SHALL start when either (a) the time gap between the next segment's `start_time` and the previous segment's `end_time` is greater than or equal to `gap_threshold_seconds`, or (b) the next segment's `speaker` differs from the current paragraph's speaker. An empty input array SHALL return an empty array without throwing.

#### Scenario: Single paragraph when segments are continuous and same speaker

- **GIVEN** segments S1(end=10.0, speaker=A), S2(start=10.5, end=15.0, speaker=A)
- **WHEN** `aggregateParagraphs([S1, S2], { gap_threshold_seconds: 1.5 })` is called
- **THEN** the result SHALL contain exactly one paragraph containing both S1 and S2

#### Scenario: Gap exceeding threshold splits paragraphs

- **GIVEN** segments S1(end=10.0, speaker=A), S2(start=12.0, end=15.0, speaker=A)
- **WHEN** `aggregateParagraphs([S1, S2])` is called with default threshold
- **THEN** the result SHALL contain exactly two paragraphs, the first containing S1 and the second containing S2

##### Example: gap boundary cases

| Prev end | Next start | Gap | Default threshold | Split? |
|----------|-----------|-----|-------------------|--------|
| 10.0 | 11.0 | 1.0 | 1.5 | no |
| 10.0 | 11.5 | 1.5 | 1.5 | yes |
| 10.0 | 12.0 | 2.0 | 1.5 | yes |

#### Scenario: Speaker change splits paragraphs regardless of gap

- **GIVEN** segments S1(end=10.0, speaker=A), S2(start=10.1, end=15.0, speaker=B)
- **WHEN** `aggregateParagraphs([S1, S2])` is called
- **THEN** the result SHALL contain exactly two paragraphs, split at the speaker boundary

#### Scenario: Empty input returns empty array

- **WHEN** `aggregateParagraphs([])` is called
- **THEN** the function SHALL return `[]` and SHALL NOT throw

---
### Requirement: TranscriptPage and SourceCard share the same paragraph aggregation

`TranscriptPage` and the source / citation cards used by the Chat and Semantic tabs SHALL both invoke `aggregateParagraphs` to render paragraph-level text from `transcript_segments`. Neither component SHALL implement its own segment-merging or paragraph-splitting logic. Both consumers SHALL use the same default `gap_threshold_seconds` of 1.5 unless explicitly overridden by the user (no user-facing override is in scope for this change).

#### Scenario: Identical inputs produce identical paragraph splits in both views

- **GIVEN** the same array of transcript segments
- **WHEN** TranscriptPage and a Chat-tab source card both render those segments
- **THEN** the paragraph splits SHALL be identical between the two views (same paragraph count, same start_time and end_time per paragraph)
