## ADDED Requirements

### Requirement: Lexical query builder SHALL filter stop-words from jieba token stream

The lexical tsquery builder (`_build_ts_query` in `backend/app/services/rag.py`) SHALL maintain a module-level immutable set of stop-words covering high-frequency Chinese particles, pronouns, interrogatives, modal verbs, and numerals, plus common English stop-words. After tokenizing the user question via jieba and filtering pure-punctuation tokens, the builder SHALL skip any token whose string is present in the stop-word set before joining the remaining tokens into the OR-joined tsquery string. The stop-word set SHALL be defined as a Python `frozenset[str]` so that consumers cannot mutate it at runtime.

#### Scenario: stop-word tokens are removed from the OR query

- **WHEN** the user question is "迪拉胖在 EP134 為什麼不挑一首振奮的開工歌？他選的歌想表達什麼概念？"
- **THEN** the resulting tsquery string SHALL NOT contain any of the tokens `的`, `不`, `在`, `為`, `什麼`, `一首`
- **AND** the resulting tsquery SHALL still contain content-bearing tokens such as `迪拉胖`, `EP134`, `振奮`, `開工歌`, `概念`

#### Scenario: all-stop-word question returns None

- **WHEN** the user question is "為什麼？"
- **THEN** the builder SHALL return `None`
- **AND** the calling retrieve pipeline SHALL fall back to the semantic-only path (preserving the existing fallback behavior)

#### Scenario: stop-word set is immutable

- **WHEN** consumer code attempts to add or remove an element from the stop-word set
- **THEN** the operation SHALL raise `AttributeError` because the set is a `frozenset`

### Requirement: Lexical query builder SHALL drop single-character tokens

The lexical tsquery builder SHALL skip any token whose character length is less than 2 after stop-word filtering. This rule applies uniformly to CJK and non-CJK single characters. Multi-character tokens whose visible length is 2 or more SHALL be retained.

#### Scenario: CJK single-character tokens are dropped

- **WHEN** jieba tokenization yields tokens `["的", "我", "去"]` after upstream cleanup
- **THEN** the builder SHALL produce an empty cleaned token list and return `None`

#### Scenario: multi-character English tokens are preserved

- **WHEN** the user question contains the tokens `EP134` and `RAG`
- **THEN** the builder SHALL retain both tokens in the resulting tsquery (both have length ≥ 2)

#### Scenario: stop-word filter and length filter run in order

- **WHEN** the token list after punctuation stripping is `["什麼", "是", "RAG"]`
- **THEN** the stop-word filter SHALL remove `什麼` and `是` first, then the length filter SHALL leave `RAG` (length 3) intact
- **AND** the final tsquery SHALL be `RAG`

### Requirement: Lexical pool size SHALL shrink to a tractable scale after filters apply

When the new stop-word and length filters are applied to the b20 EP134 reference query "迪拉胖在 EP134 為什麼不挑一首振奮的開工歌？他選的歌想表達什麼概念？", the resulting OR-joined tsquery, when evaluated against the production `transcript_chunks` table scoped to the parent show, SHALL match strictly fewer than 1,000 chunks (down from 39,323 in the pre-change baseline). This bounds the lexical pool noise such that ground-truth chunks ranked by `ts_rank` have a realistic chance of entering the `LIMIT :per_side=50` window.

#### Scenario: b20 reference query lexical match count is bounded

- **WHEN** the b20 reference query is tokenized and passed through the updated `_build_ts_query`
- **AND** the resulting tsquery is evaluated against `transcript_chunks` scoped to the show containing EP134
- **THEN** the matching chunk count SHALL be strictly less than 1,000

#### Scenario: ground-truth chunks enter lexical pool top 50

- **WHEN** the b20 reference query is run through the updated retrieval pipeline against the production database
- **THEN** at least one of the ground-truth chunks `9543a933-69bd-47a6-b9b8-2024ec41b7ba` (start_time 1790.18) or `f6cd079f-20dc-4d14-9e9a-54280fd2d2e4` (start_time 1808.78) SHALL appear in the lexical pool top-50 ranked by `ts_rank`
