## ADDED Requirements

### Requirement: Topic candidate selection includes transcript-chunk matches

The system SHALL include transcript-chunk matches as a candidate source when `find_episodes_by_topic` / `find_episodes_by_topic_with_source` selects candidate episodes. An episode SHALL be a candidate when it matches the topic tsquery via its title, any of its description chunks, OR any of its transcript chunks. The transcript-chunk source SHALL be controlled by a default-on boolean setting `enable_transcript_topic_prefilter`; when the setting is `False`, candidate selection SHALL be bit-equivalent to the prior title-plus-description behavior. The recency-listing topic filter (`find_episodes_by_recency`) is out of scope for this requirement and retains the prior title-plus-description behavior.

#### Scenario: Transcript-buried answer episode becomes a candidate

- **WHEN** a topic's discriminating tokens appear in an episode's transcript chunks but not in its title or description
- **AND** `enable_transcript_topic_prefilter` is `True`
- **THEN** that episode SHALL be included in the candidate set returned by `find_episodes_by_topic`

#### Scenario: Flag off preserves prior behavior

- **WHEN** `enable_transcript_topic_prefilter` is `False`
- **THEN** candidate selection SHALL match the prior title-plus-description-chunk behavior with no transcript-chunk source

### Requirement: Transcript candidate source is guarded against non-discriminative over-selection

The system SHALL guard the transcript-chunk candidate source so a single common token (for example a host name appearing across most episodes) cannot select the entire show. The transcript-chunk source SHALL be applied only when the topic yields at least two tokens after the existing jieba length filter, topic stop-words, and show-name-term removal. The system SHALL cap the episodes contributed by the transcript source to the top `transcript_prefilter_cap` episodes ranked by best transcript-chunk `ts_rank`; this cap is the primary over-selection guard. The guard SHALL NOT depend on a host registry, which does not exist; a host name is not necessarily present in the show title.

#### Scenario: Single token does not trigger transcript source

- **WHEN** a topic reduces to fewer than two tokens after filtering
- **THEN** the transcript-chunk candidate source SHALL NOT be applied
- **AND** candidate selection SHALL match the prior title-plus-description-chunk behavior

#### Scenario: Transcript source is capped by ts_rank

- **WHEN** more than `transcript_prefilter_cap` episodes match the topic via transcript chunks
- **THEN** only the top `transcript_prefilter_cap` episodes by best transcript-chunk `ts_rank` SHALL be contributed by the transcript source
