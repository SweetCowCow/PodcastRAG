## MODIFIED Requirements

### Requirement: aggregateParagraphs util produces paragraphs by silence gap, speaker change, max duration, or sentence end

The frontend SHALL expose a pure function `aggregateParagraphs(segments, opts)` where `segments` is an array of objects each containing `text`, `start_time`, `end_time`, and `speaker` (and arbitrary other fields preserved on each `segment_ids` reference), and `opts` accepts `gap_threshold_seconds` (number, default 1.5), `max_paragraph_seconds` (number, default 45), and `min_paragraph_seconds` (number, default 15). The function SHALL return an array of paragraph objects each containing `paragraph_text` (segments joined by single spaces, or directly concatenated when the boundary is between CJK characters), `start_time` (first segment's start), `end_time` (last segment's end), `speaker` (the shared speaker for that paragraph), and `segment_ids` (UUIDs of contained segments in order). A new paragraph SHALL start when ANY of the following four conditions is met (evaluated in order; first match wins):

- (a) the time gap between the next segment's `start_time` and the previous segment's `end_time` is greater than or equal to `gap_threshold_seconds`
- (b) the next segment's `speaker` is non-null AND the current paragraph's speaker is non-null AND they differ
- (c) the cumulative duration of the current paragraph (`current.end_time - current.start_time`) is greater than or equal to `max_paragraph_seconds`
- (d) the last character of the current paragraph's text is one of the sentence-end punctuation marks `。！？.!?` AND the cumulative duration of the current paragraph is greater than or equal to `min_paragraph_seconds`

An empty input array SHALL return an empty array without throwing. Inputs where every segment has `speaker == null` and consecutive segments are continuous (gap = 0) SHALL still produce multiple paragraphs via conditions (c) and (d), and SHALL NOT collapse into a single paragraph regardless of input length.

#### Scenario: Single paragraph when segments are continuous, same speaker, and below max duration

- **GIVEN** segments S1(start=0, end=10.0, speaker=A, text="嗨大家"), S2(start=10.5, end=15.0, speaker=A, text="今天聊")
- **WHEN** `aggregateParagraphs([S1, S2], { gap_threshold_seconds: 1.5, max_paragraph_seconds: 45, min_paragraph_seconds: 15 })` is called
- **THEN** the result SHALL contain exactly one paragraph containing both S1 and S2

#### Scenario: Gap exceeding threshold splits paragraphs

- **GIVEN** segments S1(end=10.0, speaker=A), S2(start=12.0, end=15.0, speaker=A)
- **WHEN** `aggregateParagraphs([S1, S2])` is called with default options
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

#### Scenario: Max paragraph duration forces a split when no gap and no speaker label

- **GIVEN** 50 segments each 1 second long, all `speaker=null`, all `end(prev) == start(next)` (gap=0), no sentence-end punctuation in any text
- **WHEN** `aggregateParagraphs(segments, { max_paragraph_seconds: 45 })` is called
- **THEN** the result SHALL contain at least 2 paragraphs (50 seconds total > 45 second cap)
- **AND** each paragraph SHALL span at most `max_paragraph_seconds + 1` seconds in cumulative duration

#### Scenario: Sentence-end punctuation splits when paragraph has accumulated min duration

- **GIVEN** 20 segments totalling 30 seconds, all `speaker=null`, gap=0, where the segment at cumulative 16-second mark ends with `。`
- **WHEN** `aggregateParagraphs(segments, { min_paragraph_seconds: 15, max_paragraph_seconds: 45 })` is called
- **THEN** a paragraph boundary SHALL fall after the `。`-ending segment (cumulative ≥ 15 seconds and sentence-end matched)
- **AND** the result SHALL contain at least 2 paragraphs

#### Scenario: Sentence-end punctuation does NOT split below min duration

- **GIVEN** segments S1(start=0, end=3, speaker=null, text="對。"), S2(start=3, end=8, speaker=null, text="然後呢")
- **WHEN** `aggregateParagraphs([S1, S2], { min_paragraph_seconds: 15 })` is called
- **THEN** the result SHALL contain exactly one paragraph (cumulative 3 seconds < 15 second floor)

#### Scenario: Empty input returns empty array

- **WHEN** `aggregateParagraphs([])` is called
- **THEN** the function SHALL return `[]` and SHALL NOT throw

#### Scenario: 80-minute Whisper word-level transcript produces multiple paragraphs

- **GIVEN** 2500 segments all with `speaker=null`, consecutive `end(prev) == start(next)` (gap=0), covering 80 minutes (4800 seconds)
- **WHEN** `aggregateParagraphs(segments)` is called with default options
- **THEN** the result SHALL contain at least 20 paragraphs
- **AND** the result SHALL NOT be a single paragraph regardless of segment count
