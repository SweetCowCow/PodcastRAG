## MODIFIED Requirements

### Requirement: Correction backfill recomputes affected chunks

The backfill operation SHALL apply correction rules to existing transcripts and recompute the affected chunks (text + embeddings + tsvector). For each segment whose text changes, the system SHALL preserve the pre-correction text in `original_text` once (set only when `original_text` is null; never overwritten). For each affected transcript, the system SHALL set `original_content` once (when null) to the pre-correction content and SHALL update `transcripts.content` to reflect the corrections, so the full-episode text stays consistent with the segments. The dry-run preview SHALL remain read-only and SHALL NOT write `original_text`, `original_content`, or `content`.

#### Scenario: Backfill preserves original and syncs content

- **GIVEN** an existing transcript with an applicable enabled rule whose `wrong` appears in its segments and content
- **WHEN** a non-dry-run backfill runs
- **THEN** each changed segment's `original_text` SHALL hold its pre-correction text, the transcript's `original_content` SHALL hold its pre-correction content, and `transcripts.content` SHALL contain the corrected text

#### Scenario: Dry-run writes nothing

- **WHEN** a dry-run backfill preview runs
- **THEN** no `original_text`, `original_content`, `content`, segment, or chunk values SHALL be written

## ADDED Requirements

### Requirement: Episode transcript restore to original

The backend SHALL expose an admin-only endpoint to restore an episode's transcript to its original ASR text. Restore SHALL set each segment's `text` back to its `original_text` where `original_text` is non-null, set `content` back to `original_content` where non-null, recompute the chunks affected by the reverted segments (text + embeddings + tsvector), and then clear `original_text` on those segments and `original_content` on the transcript (returning the episode to an uncorrected, no-snapshot state). An episode with no preserved original SHALL return a success result reporting zero affected segments rather than an error.

#### Scenario: Restore reverts corrections and clears snapshot

- **GIVEN** an episode whose segments were corrected and have `original_text` set
- **WHEN** an admin restores the episode
- **THEN** the segments' `text` and the transcript's `content` SHALL match the original ASR text, the affected chunks SHALL be recomputed, and `original_text`/`original_content` SHALL be cleared

#### Scenario: Restore with no snapshot is a no-op

- **GIVEN** an episode with no segment having `original_text`
- **WHEN** an admin restores the episode
- **THEN** the endpoint SHALL return success with zero affected segments

#### Scenario: Restore requires admin

- **WHEN** a non-admin calls the restore endpoint
- **THEN** the API SHALL reject the request
