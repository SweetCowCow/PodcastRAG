## MODIFIED Requirements

### Requirement: Transcript candidate source is guarded against non-discriminative over-selection

The system SHALL guard the transcript-chunk candidate source so a single common token (for example a host name appearing across most episodes) cannot select the entire show. The transcript-chunk source SHALL be applied only when the effective topic tokens number at least two after the existing jieba length filter, topic stop-words, and show-name-term removal.

The effective topic tokens SHALL be derived as follows so that the agent placing only a single entity in the `topic` argument (while the discriminating content sits in the `query` argument) does not silently disable the transcript source:

- Let `topic_tokens` be the discriminating tokens of the `topic` argument.
- WHEN `topic_tokens` has at least two tokens, the effective topic tokens SHALL be exactly `topic_tokens` (the `query` argument SHALL NOT influence selection, preserving prior behavior for focused topics).
- WHEN `topic_tokens` has fewer than two tokens AND a non-empty `query` argument is provided, the effective topic tokens SHALL be the discriminating tokens of the combined `topic` and `query` text, deduplicated.
- Otherwise the effective topic tokens SHALL be `topic_tokens`.

The OR-tsquery and the coverage arm's per-token array SHALL both be built from the same effective topic tokens. The system SHALL contribute episodes from the transcript source as the union of two capped arms, deduplicated by episode id:

1. a `ts_rank` arm — the top `transcript_prefilter_cap` episodes ranked by best transcript-chunk `ts_rank` over the topic OR-tsquery (this preserves single-token-relevant episodes for breadth-oriented topics); and
2. a coverage arm — the top `transcript_prefilter_cap` episodes ranked by the count of DISTINCT topic tokens matched in their transcript chunks, with the sum of per-token best `ts_rank` as the tie-break (this surfaces narrative episodes that cover multiple topic tokens but whose single best `ts_rank` is diluted by common tokens).

The combined contribution is therefore at most `2 × transcript_prefilter_cap` episodes. The guard SHALL NOT depend on a host registry, which does not exist; a host name is not necessarily present in the show title. When the transcript source is not applied (flag off, or fewer than two effective topic tokens), candidate selection SHALL be bit-equivalent to the prior title-plus-description behavior. The `query`-fallback derivation SHALL be governed by the same `enable_transcript_topic_prefilter` setting; no additional setting is introduced.

#### Scenario: Single token does not trigger transcript source

- **WHEN** a topic reduces to fewer than two tokens after filtering
- **AND** no `query` argument is provided (or it also yields fewer than two combined discriminating tokens)
- **THEN** the transcript-chunk candidate source SHALL NOT be applied
- **AND** candidate selection SHALL match the prior title-plus-description-chunk behavior

#### Scenario: Thin topic plus discriminating query triggers transcript source

- **GIVEN** a `topic` argument that yields fewer than two discriminating tokens (for example a single entity name)
- **AND** a `query` argument whose combined discriminating tokens with the topic number at least two
- **WHEN** `enable_transcript_topic_prefilter` is `True`
- **THEN** the transcript-chunk candidate source SHALL be applied using the combined discriminating tokens
- **AND** the OR-tsquery and the coverage arm's per-token array SHALL both be built from those combined tokens

#### Scenario: Focused topic ignores query

- **GIVEN** a `topic` argument that yields at least two discriminating tokens
- **WHEN** the transcript source is applied
- **THEN** the effective topic tokens SHALL equal the topic's discriminating tokens
- **AND** the `query` argument SHALL NOT change which episodes are selected

#### Scenario: Transcript source contributes the union of ts_rank and coverage arms

- **WHEN** more than `transcript_prefilter_cap` episodes match the topic via transcript chunks
- **THEN** the transcript source SHALL contribute the union of (the top `transcript_prefilter_cap` episodes by best transcript-chunk `ts_rank`) and (the top `transcript_prefilter_cap` episodes by distinct-token coverage with sum-of-per-token-`ts_rank` tie-break)
- **AND** the contributed set SHALL be deduplicated by episode id

#### Scenario: Narrative GT episode surfaces without dropping single-token enumeration episodes

- **GIVEN** a topic with multiple discriminating tokens where the answer episode's transcript covers most of the tokens but its single best `ts_rank` is outranked by episodes heavy in one common token
- **WHEN** the transcript source is applied
- **THEN** the multi-token-covering answer episode SHALL be contributed via the coverage arm
- **AND** an episode that matches only one of the topic tokens but ranks within the top `transcript_prefilter_cap` by `ts_rank` SHALL still be contributed via the `ts_rank` arm
