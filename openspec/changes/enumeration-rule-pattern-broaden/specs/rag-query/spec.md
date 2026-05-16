## MODIFIED Requirements

### Requirement: Cross-episode enumeration response shape

The chat endpoint response SHALL include an optional `enumeration_episodes` field containing a list of episode references when the query is an enumeration-type question, AND an optional `enumeration_total: int | None` field carrying the full count (which MAY exceed the number of entries when the grounding block truncates).

#### Scenario: Enumeration episodes returned alongside chunk citations

- **WHEN** chat query extracts non-empty guests entity AND the show has 4 episodes matching `guests @> :guest_list`
- **THEN** the response body SHALL contain `enumeration_episodes` with all 4 entries, each `{episode_id, title, published_at, guests, ai_summary}`
- **AND** `enumeration_total` SHALL equal 4
- **AND** `citations` SHALL still contain the answer-model-cited chunks (separate field)

#### Scenario: Non-enumeration query has null enumeration fields

- **WHEN** chat query produces empty entities AND no enumeration rule pattern match
- **THEN** the response body SHALL set `enumeration_episodes = null` AND `enumeration_total = null`

#### Scenario: Empty filter result keeps fields populated

- **WHEN** chat query triggers enumeration (entity OR rule pattern) but the filter SQL yields 0 episodes
- **THEN** `enumeration_episodes` SHALL be `[]` (empty list) AND `enumeration_total` SHALL be 0
- **AND** the response body SHALL NOT set these fields to `null` (null vs empty list distinguishes "did not trigger" from "triggered but no match")

#### Scenario: Enumeration rule pattern triggers topic-filtered enumeration

The rule pattern SHALL accept multiple Mandarin question structures that name 集 (episode) as the object being enumerated:

- forward structure: `[哪那]幾集` / `[哪那]集` / `[哪那]些集` — covers "哪幾集", "哪集", "哪些集" and the common "那"-typo equivalents
- reversed structure: `集數?有[哪那]些` — covers "集數有哪些", "集有哪些", "集數有那些", "集有那些"

The pattern SHALL NOT trigger on bare "[哪那]些" without an adjacent "集" — phrases like "主持人有哪些" / "歌單有哪些" risk false positives because the subject (主持人 / 歌單) is enumerable in isolation, not necessarily as an episode list.

- **WHEN** chat query contains a substring matching `[哪那]幾集 / [哪那]集 / [哪那]些集 / 集數?有[哪那]些` AND entity extractor returns empty entities
- **THEN** the endpoint SHALL jieba-tokenise the question, drop tokens in `TOPIC_STOPWORDS`, AND use the remaining multi-char terms as topic_terms for the topic-filter SQL
- **AND** `enumeration_episodes` SHALL contain only episodes whose `episode_description_chunks.text_tsvector` matches the topic_terms
- **AND** the endpoint SHALL NOT fall back to "list every episode of the show"

#### Scenario: Reversed-structure question triggers enumeration

- **GIVEN** chat query `"節目裡有講過高雄美食的集數有哪些？"`
- **WHEN** the chat endpoint evaluates the rule pattern
- **THEN** the `集數?有[哪那]些` arm SHALL match the substring `"集數有哪些"`
- **AND** the runner SHALL dispatch to the topic-filter SQL with topic_terms derived from the question
- **AND** `enumeration_episodes` SHALL NOT be `null`

#### Scenario: Forward-structure question still triggers enumeration (regression guard)

- **GIVEN** chat query `"節目裡有哪些集是歌單？"`
- **WHEN** the chat endpoint evaluates the rule pattern
- **THEN** the existing `[哪那]些集` arm SHALL still match `"哪些集"`
- **AND** behavior SHALL be byte-identical to runs before this pattern broadening shipped

#### Scenario: "有哪些" without adjacent 集 does NOT trigger (false-positive guard)

- **GIVEN** chat query `"主持人有哪些人？"` (about the show's hosts, not episodes)
- **WHEN** the chat endpoint evaluates the rule pattern
- **THEN** NO arm of the pattern SHALL match (the `集` requirement protects against this case)
- **AND** `enumeration_episodes` SHALL remain `null` unless the LLM entity extractor independently surfaces guests/topics/date entities
