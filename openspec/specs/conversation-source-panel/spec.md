# conversation-source-panel Specification

## Purpose

TBD - created by archiving change 'landing-and-mode-orchestration-redesign'. Update Purpose after archive.

## Requirements

### Requirement: Chat tab renders a single episode-grouped source panel

The Chat tab of `QueryPage` SHALL render answer citations in exactly one source panel below the AI answer. The panel SHALL replace the prior dual-region layout that combined a chip strip with a separate SourceCard list. Citations SHALL be grouped by `episode_id`; each episode group SHALL be a single visual block containing the episode title once at the top, followed by the chunks from that episode rendered as SourceCards. Each episode group SHALL be collapsible by clicking the episode title.

#### Scenario: Citations grouped by episode

- **GIVEN** an answer with citations C1(ep=A), C2(ep=B), C3(ep=A), C4(ep=A)
- **WHEN** the source panel renders
- **THEN** the panel SHALL contain exactly two episode groups: A (containing C1, C3, C4) and B (containing C2)
- **AND** the episode A group SHALL display the episode title exactly once
- **AND** there SHALL NOT be a separate chip strip duplicating the episode list

#### Scenario: Clicking episode title collapses the group

- **GIVEN** an expanded episode group containing two SourceCards
- **WHEN** the user clicks the episode title
- **THEN** the SourceCards in that group SHALL be hidden
- **AND** the episode title SHALL remain visible with an indicator that it can be re-expanded

---
### Requirement: Source panel header reports unique-episode and total-chunk counts

The source panel SHALL render a header above all episode groups with the bilingual text 答案參考來源（共 N 集 · M 段引用） (`zh`) / Answer sources (N episodes · M citations) (`en`), where N is the count of unique `episode_id` values across the citations and M is the total number of citation chunks.

#### Scenario: Header counts match the citation set

- **GIVEN** an answer with citations from 2 distinct episodes totalling 5 chunks
- **WHEN** the source panel renders in `zh`
- **THEN** the header SHALL contain the substring `共 2 集` and the substring `5 段引用`

##### Example: header substitution table

| Unique episodes | Total chunks | zh header |
|-----------------|--------------|-----------|
| 1 | 1 | 答案參考來源（共 1 集 · 1 段引用） |
| 2 | 5 | 答案參考來源（共 2 集 · 5 段引用） |
| 3 | 7 | 答案參考來源（共 3 集 · 7 段引用） |

---
### Requirement: Source panel uses shared paragraph aggregation for chunk text

Each SourceCard inside the source panel SHALL render its transcript text by applying `aggregateParagraphs` to the chunk's `transcript_segments`. The SourceCard SHALL NOT implement its own segment-merging logic. The visual paragraph splits inside a SourceCard SHALL match the splits seen on TranscriptPage for the same segments.

#### Scenario: SourceCard paragraph splits match TranscriptPage

- **GIVEN** a chunk whose `transcript_segments` would split into 3 paragraphs under `aggregateParagraphs`
- **WHEN** that chunk renders inside a SourceCard
- **THEN** the SourceCard SHALL display exactly 3 paragraphs with the same boundaries as TranscriptPage
