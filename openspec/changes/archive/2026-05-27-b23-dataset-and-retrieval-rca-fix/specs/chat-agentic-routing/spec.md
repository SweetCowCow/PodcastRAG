## ADDED Requirements

### Requirement: `find_episodes_by_topic` SHALL dispatch to a guest-index path when topic tokens match known guest names

When `find_episodes_by_topic(show_id, topic_terms)` receives a `topic_terms` list whose tokens (after the existing jieba tokenisation) contain at least two members that exist in the show's set of known guest names (collected by scanning `episodes.guests` JSONB string-array column), the function SHALL execute a guest-index SQL path **in addition to** the existing title / description tsquery path and SHALL return the union (deduplicated) of both result sets.

The guest-index SQL path SHALL match episodes whose `episodes.guests` JSONB string-array contains at least one entry equal to (case-sensitive) any of the matched guest tokens. The returned list SHALL preserve the existing `ORDER BY e.published_at DESC NULLS LAST` semantics.

When fewer than two tokens match known guest names, the function SHALL behave identically to its prior implementation (title / description tsquery only). The fallback contract for empty `topic_terms` SHALL remain unchanged (returns `[]`).

#### Scenario: Two guest tokens trigger guest-index dispatch

- **GIVEN** the show has episode A with `guests=["Leo 王"]` and episode B with `guests=["小老虎","Leo 王"]`
- **AND** episode C has `guests=[]` but its title contains the string "Leo"
- **WHEN** `find_episodes_by_topic(show_id, ["迪拉 Leo 王"])` is invoked
- **THEN** the jieba-tokenised topic resolves to tokens including `"迪拉"`, `"Leo"`, `"王"`
- **AND** because `"Leo"` and `"王"` (or `"Leo 王"` after a single-string match) appear in the show's known-guest set in at least two distinct guest entries
- **THEN** the function SHALL run the guest-index SQL path
- **AND** the returned list SHALL include episode A and episode B
- **AND** the returned list MAY include episode C if the existing title tsquery path also matched

#### Scenario: Single guest token preserves prior behaviour

- **GIVEN** the show has episode A with `guests=["馬世芳"]`
- **WHEN** `find_episodes_by_topic(show_id, ["馬世芳的家常味"])` is invoked
- **AND** only one token (`"馬世芳"`) matches the known-guest set after tokenisation
- **THEN** the function SHALL NOT execute the guest-index SQL path
- **AND** SHALL return the same result as the prior implementation (title / description tsquery only)

#### Scenario: No guest tokens preserve prior behaviour

- **GIVEN** the topic terms `["家常味"]` contain no tokens matching any known guest name
- **WHEN** `find_episodes_by_topic` is invoked
- **THEN** the function SHALL execute only the existing title / description tsquery path

### Requirement: `search_with_topic_prefilter` envelope SHALL expose `prefilter_source` for observability

The `search_with_topic_prefilter` tool's response envelope SHALL include a `prefilter_source` field whose value is one of the strings `"topic_index"`, `"guest_index"`, or `"merged"`. The field SHALL reflect which internal dispatch path produced the candidate episode set.

When the candidate set comes solely from the prior title / description tsquery path, `prefilter_source` SHALL be `"topic_index"`. When the candidate set comes solely from the guest-index SQL path (i.e., the title path returned no candidates), `prefilter_source` SHALL be `"guest_index"`. When both paths contributed, `prefilter_source` SHALL be `"merged"`.

When the candidate set is empty and the tool falls back to `rag.retrieve_hybrid` without `episode_id_filter`, `prefilter_source` SHALL still be set to the path that was attempted (defaulting to `"topic_index"` when neither path matched), and `fallback_to_full_pool` SHALL remain `true`.

#### Scenario: Guest-index path triggers `prefilter_source=guest_index`

- **GIVEN** the LLM invokes `search_with_topic_prefilter(topic="迪拉 Leo 王", query="第一次見面的故事")`
- **AND** `find_episodes_by_topic` returns candidates only via the guest-index path (title tsquery returned empty)
- **WHEN** the tool builds its response envelope
- **THEN** the envelope SHALL include `"prefilter_source": "guest_index"`
- **AND** `prefilter_episode_count` SHALL reflect the guest-path candidate count

#### Scenario: Merged path triggers `prefilter_source=merged`

- **GIVEN** both the title path and the guest-index path contribute distinct candidate episodes
- **WHEN** `find_episodes_by_topic` returns the union
- **THEN** the envelope SHALL include `"prefilter_source": "merged"`

#### Scenario: Topic-only path preserves prior envelope shape semantics

- **GIVEN** a query without any guest-name token
- **WHEN** the tool runs the existing title / description tsquery only
- **THEN** the envelope SHALL include `"prefilter_source": "topic_index"`
- **AND** all other existing envelope fields (`prefilter_episode_count`, `fallback_to_full_pool`, `rerank_applied`, `rerank_input_count`) SHALL retain their prior semantics
