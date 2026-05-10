## ADDED Requirements

### Requirement: Search and query responses include context, highlights, and AI summary excerpt

The backend `POST /shows/{show_id}/search` and `POST /shows/{show_id}/query` endpoints SHALL include four additional fields on every result/citation entry: `before_text` (string, the concatenated text of the up to two preceding `transcript_segments` rows joined by single spaces, or empty string when no preceding segments exist), `after_text` (same shape for the up to two following segments), `highlights` (string containing PostgreSQL `ts_headline()` output that wraps query-token matches in `<mark>...</mark>` tags using the same jieba-backed tsvector configuration that retrieval uses, with no other HTML allowed), and `ai_summary_excerpt` (string, the first 60 characters of the episode's `ai_summary` column followed by `…` if truncation occurred, or empty string when no summary exists). For description-source entries (`source="description"`), `before_text` and `after_text` SHALL be empty strings (descriptions have no segment-level neighbours). The response SHALL include a top-level `sources_schema_version` integer set to `1` to support future cache invalidation.

#### Scenario: Transcript source includes two-segment context

- **GIVEN** a transcript chunk whose middle region starts at segment `s5` and ends at segment `s7`, and segments `s3`, `s4` precede `s5` and `s8`, `s9` follow `s7` within the same transcript
- **WHEN** the search endpoint returns this chunk in the response
- **THEN** the entry's `before_text` SHALL equal `"<text of s3> <text of s4>"`
- **AND** the entry's `after_text` SHALL equal `"<text of s8> <text of s9>"`

#### Scenario: First chunk has empty before_text

- **GIVEN** a transcript chunk whose middle region begins at segment `s1` (the first segment of the transcript)
- **WHEN** the chunk is returned in a response
- **THEN** the entry's `before_text` SHALL equal `""`
- **AND** the entry's `after_text` SHALL contain up to two following segments concatenated

#### Scenario: Description source has empty context fields

- **WHEN** a description chunk (`source="description"`) is returned
- **THEN** the entry's `before_text` SHALL equal `""`
- **AND** the entry's `after_text` SHALL equal `""`
- **AND** the entry's `highlights` SHALL still contain `ts_headline()` output computed against the description text

#### Scenario: Highlights wrap matched tokens

- **GIVEN** a chunk whose stored text contains the substring `歌單環節` and the user's query is `這集有歌單嗎`
- **WHEN** the response is constructed
- **THEN** the entry's `highlights` SHALL contain the substring `<mark>歌單</mark>` (or a longer matched span depending on jieba tokenisation) inside a fragment of surrounding context
- **AND** the entry's `highlights` SHALL NOT contain any HTML tag other than `<mark>`

#### Scenario: AI summary excerpt truncates with ellipsis

- **GIVEN** an episode whose `ai_summary` column starts with the 80-character string `迪拉胖在這集邀請了顏色一起聊...（共 80 字）`
- **WHEN** a chunk from this episode is returned
- **THEN** the entry's `ai_summary_excerpt` SHALL contain the first 60 characters of `ai_summary` followed by exactly one `…` character

#### Scenario: Episode without AI summary returns empty excerpt

- **WHEN** a chunk from an episode whose `ai_summary` is NULL or empty is returned
- **THEN** the entry's `ai_summary_excerpt` SHALL equal `""`

#### Scenario: Response carries sources schema version

- **WHEN** any successful response is returned from `/shows/{show_id}/search` or `/shows/{show_id}/query`
- **THEN** the response body SHALL include a top-level integer field `sources_schema_version` equal to `1`

### Requirement: LLM answer prompt enforces citation, faithfulness, and refusal

The backend `POST /shows/{show_id}/query` answer prompt SHALL be reconstructed so that the configured answer model receives: (a) a system instruction enumerating retrieved sources as a numbered list `[1] [2] [3] …` matching the order returned by hybrid retrieval; (b) a directive that every factual claim in the answer SHALL end with a bracketed reference of the form `[N]` for a single source or `[N,M,...]` for multi-source synthesis; (c) a directive that the model SHALL NOT introduce facts absent from the supplied sources, and SHALL answer 「找不到相關內容，請改用其他關鍵字」 (if `lang=zh`) or `"No relevant content was found. Please try different keywords."` (if `lang=en`) when retrieval returns no results or when no source supports the question. The prompt SHALL preserve the existing requirement to emit JSON containing `answer` and `used_chunk_ids` (see existing requirement "Chat endpoint answers with citations using Tier 2 RAG").

#### Scenario: Answer cites single source

- **GIVEN** retrieval returns three sources numbered `[1] [2] [3]`
- **AND** the answer model produces the sentence `迪拉胖第一次來上節目是 EP1[1]`
- **WHEN** the endpoint serialises the response
- **THEN** the `answer` field SHALL contain the substring `[1]` immediately after the relevant claim

#### Scenario: Answer cites multiple sources

- **GIVEN** retrieval returns four sources `[1] [2] [3] [4]`
- **AND** the answer model produces the sentence `他在 EP1 與 EP134 都聊過這個話題[1,3]`
- **WHEN** the endpoint serialises the response
- **THEN** the `answer` field SHALL contain the substring `[1,3]` immediately after the relevant claim

#### Scenario: Empty retrieval triggers explicit refusal in zh

- **GIVEN** the user's `lang` cookie is `zh` and hybrid retrieval returns zero chunks
- **WHEN** the answer model is invoked with the empty sources list
- **THEN** the `answer` field SHALL contain the substring `找不到相關內容`
- **AND** `citations` SHALL be an empty array

#### Scenario: Empty retrieval triggers explicit refusal in en

- **GIVEN** the user's `lang` cookie is `en` and hybrid retrieval returns zero chunks
- **WHEN** the answer model is invoked with the empty sources list
- **THEN** the `answer` field SHALL contain the substring `No relevant content was found`

#### Scenario: Faithfulness gate blocks archive on regression

- **GIVEN** the R1.2 mini-set (`backend/eval/datasets/this-not-that-cool.json`) Faithfulness median was `F_pre` before the prompt change
- **AND** the post-change Faithfulness median is `F_post`
- **WHEN** archive readiness is evaluated
- **THEN** archive SHALL be blocked when `F_post < F_pre`

### Requirement: Citation parser strips invalid refs and degrades gracefully

The backend SHALL implement a citation parser invoked after the answer model returns. Given the raw answer string and the list of source numbers `1..N`, the parser SHALL extract every bracketed reference token of the form `[K]` or `[K,M,...]`. Tokens whose every numeric component lies in `1..N` SHALL be retained verbatim in the answer. Tokens with at least one component outside `1..N` SHALL be removed entirely (including the surrounding brackets). The parser SHALL produce a structured representation `citations_meta: [{sentence_index, ref_ids: [...]}, ...]` mapped per sentence (sentences split on `。`, `！`, `？`, `.`, `!`, `?`) and SHALL include `citations_meta` in the response body for future R2.2 inline rendering. The original `citations` array (chunks referenced via `used_chunk_ids`) SHALL still be returned so that the frontend can render source cards even when the inline reference parsing yields nothing.

#### Scenario: Valid single ref retained

- **GIVEN** the answer text is `這集播了三首[1]`
- **AND** retrieval returned three sources
- **WHEN** the parser runs
- **THEN** the answer string SHALL remain `這集播了三首[1]`
- **AND** `citations_meta` SHALL contain one entry whose `ref_ids` equals `[1]`

#### Scenario: Out-of-range ref stripped

- **GIVEN** the answer text is `這集很精彩[5]`
- **AND** retrieval returned three sources
- **WHEN** the parser runs
- **THEN** the answer string SHALL equal `這集很精彩`
- **AND** `citations_meta` SHALL contain one entry whose `ref_ids` is an empty array

#### Scenario: Multi-ref with one invalid component drops the whole token

- **GIVEN** the answer text is `他在兩集講過[1,9]`
- **AND** retrieval returned three sources
- **WHEN** the parser runs
- **THEN** the answer string SHALL equal `他在兩集講過`
- **AND** `citations_meta` SHALL contain one entry whose `ref_ids` is an empty array

#### Scenario: No bracketed refs at all yields empty meta

- **GIVEN** the answer model returned plain prose with no `[N]` tokens
- **WHEN** the parser runs
- **THEN** the answer string SHALL be unchanged
- **AND** `citations_meta` SHALL be a list of entries each with empty `ref_ids`
- **AND** the response body SHALL still include the full `citations` array

## MODIFIED Requirements

### Requirement: Citation click navigates to transcript with highlight

The frontend ChatBubble citation badge SHALL be interactive. When a user clicks a citation badge, the application SHALL navigate to TranscriptPage for the cited episode using a URL containing the query parameter `?t=<seconds>` where `<seconds>` is the citation's `start_time` formatted with up to one decimal place. TranscriptPage SHALL parse `?t` from `window.location.search` on mount, scroll to the first segment whose `start_time` is closest to the parsed value within a ±5 second window, and apply a 3-second highlighted background that fades out. When no segment falls within the window, TranscriptPage SHALL scroll to the top of the transcript without highlighting any segment. The button label SHALL read `跳到這段內容` when `lang=zh` and `Jump to transcript` when `lang=en`.

#### Scenario: Citation badge click navigates with t URL param

- **WHEN** a user clicks a citation badge in a ChatBubble where the source's `start_time` is `252.6`
- **THEN** the application SHALL navigate to a URL whose path resolves to TranscriptPage for the cited `episode_id` and whose search string contains `t=252.6`

#### Scenario: TranscriptPage highlights segment matched within window

- **GIVEN** TranscriptPage mounts with `window.location.search` containing `t=252.6`
- **AND** the transcript contains a segment with `start_time=251.8`
- **WHEN** the page renders
- **THEN** the page SHALL scroll to the segment whose `start_time=251.8` (the closest within ±5 seconds)
- **AND** the page SHALL apply a 3-second highlighted background to that segment

#### Scenario: TranscriptPage falls back to top when no segment within window

- **GIVEN** TranscriptPage mounts with `t=900.0` but no segment has `start_time` within `[895.0, 905.0]`
- **WHEN** the page renders
- **THEN** the page SHALL scroll to the top of the transcript
- **AND** no segment SHALL be highlighted

#### Scenario: Button label respects language

- **WHEN** the language is `zh` and a citation is rendered
- **THEN** the jump button SHALL display `跳到這段內容`

- **WHEN** the language is `en` and a citation is rendered
- **THEN** the jump button SHALL display `Jump to transcript`
