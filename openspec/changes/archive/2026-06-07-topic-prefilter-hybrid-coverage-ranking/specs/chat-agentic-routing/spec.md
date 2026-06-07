## MODIFIED Requirements

### Requirement: Transcript candidate source is guarded against non-discriminative over-selection

The system SHALL guard the transcript-chunk candidate source so a single common token (for example a host name appearing across most episodes) cannot select the entire show. The transcript-chunk source SHALL be applied only when the topic yields at least two tokens after the existing jieba length filter, topic stop-words, and show-name-term removal. The system SHALL contribute episodes from the transcript source as the union of two capped arms, deduplicated by episode id:

1. a `ts_rank` arm — the top `transcript_prefilter_cap` episodes ranked by best transcript-chunk `ts_rank` over the topic OR-tsquery (this preserves single-token-relevant episodes for breadth-oriented topics); and
2. a coverage arm — the top `transcript_prefilter_cap` episodes ranked by the count of DISTINCT topic tokens matched in their transcript chunks, with the sum of per-token best `ts_rank` as the tie-break (this surfaces narrative episodes that cover multiple topic tokens but whose single best `ts_rank` is diluted by common tokens).

The combined contribution is therefore at most `2 × transcript_prefilter_cap` episodes. The guard SHALL NOT depend on a host registry, which does not exist; a host name is not necessarily present in the show title. When the transcript source is not applied (flag off, or fewer than two discriminating tokens), candidate selection SHALL be bit-equivalent to the prior title-plus-description behavior.

#### Scenario: Single token does not trigger transcript source

- **WHEN** a topic reduces to fewer than two tokens after filtering
- **THEN** the transcript-chunk candidate source SHALL NOT be applied
- **AND** candidate selection SHALL match the prior title-plus-description-chunk behavior

#### Scenario: Transcript source contributes the union of ts_rank and coverage arms

- **WHEN** more than `transcript_prefilter_cap` episodes match the topic via transcript chunks
- **THEN** the transcript source SHALL contribute the union of (the top `transcript_prefilter_cap` episodes by best transcript-chunk `ts_rank`) and (the top `transcript_prefilter_cap` episodes by distinct-token coverage with sum-of-per-token-`ts_rank` tie-break)
- **AND** the contributed set SHALL be deduplicated by episode id

#### Scenario: Narrative GT episode surfaces without dropping single-token enumeration episodes

- **GIVEN** a topic with multiple discriminating tokens where the answer episode's transcript covers most of the tokens but its single best `ts_rank` is outranked by episodes heavy in one common token
- **WHEN** the transcript source is applied
- **THEN** the multi-token-covering answer episode SHALL be contributed via the coverage arm
- **AND** an episode that matches only one of the topic tokens but ranks within the top `transcript_prefilter_cap` by `ts_rank` SHALL still be contributed via the `ts_rank` arm
