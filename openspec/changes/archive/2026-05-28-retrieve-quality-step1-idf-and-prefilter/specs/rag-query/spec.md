## ADDED Requirements

### Requirement: Transcript lexical retrieval SHALL apply corpus-derived IDF weighting to token signals

The transcript RRF retrieval path (`_TRANSCRIPT_RRF_SQL`) SHALL compute lexical chunk ranking by partitioning the query tokens into four IDF buckets (`A`/`B`/`C`/`D`) derived from per-show inverse document frequency (IDF) values cached in a dedicated `transcript_token_freq` table, and SHALL combine the per-bucket `ts_rank` scores with a fixed bucket-weight vector (A=1.0, B=0.5, C=0.2, D=0.05). Tokens with high IDF (rare in the corpus) SHALL contribute more to ranking; tokens with low IDF (common, stop-word-like) SHALL contribute less, but SHALL NOT be removed from the match predicate. The `text_tsvector @@ to_tsquery` match predicate SHALL keep using the full OR-joined token query so that all original matching chunks remain eligible for ranking.

#### Scenario: high-IDF tokens rank earlier than low-IDF tokens

- **WHEN** a query contains both a rare entity token (e.g. `迪拉胖`, IDF > 8) and a common particle token (e.g. `的`, IDF ≤ 2)
- **THEN** chunks containing the rare token SHALL receive a higher combined bucket-weighted `ts_rank` score than chunks containing only the common token
- **AND** chunks containing only the common token SHALL still appear in the lexical pool (not be filtered out)

#### Scenario: missing IDF entry falls back to neutral bucket

- **WHEN** the IDF lookup for a query token returns no row in `transcript_token_freq`
- **THEN** that token SHALL be assigned the neutral bucket `C`
- **AND** retrieval SHALL proceed without raising an exception
- **AND** a warning SHALL be logged with the missing token

#### Scenario: complete IDF table absence falls back to original ranking

- **WHEN** the `transcript_token_freq` table is empty or unreachable for a show
- **THEN** retrieval SHALL fall back to the original `ts_rank` ranking path
- **AND** the request SHALL complete successfully without raising an exception

##### Example: IDF bucket mapping

| IDF range | Bucket | Bucket weight in rank sum |
|---|---|---|
| IDF > 8 | A | 1.0 |
| 5 < IDF ≤ 8 | B | 0.5 |
| 2 < IDF ≤ 5 | C | 0.2 |
| IDF ≤ 2 | D | 0.05 |

### Requirement: IDF cache SHALL be refreshable via admin endpoint

The system SHALL expose an admin-only endpoint that triggers a batch refresh of `transcript_token_freq` for a given `show_id` (or all shows). The refresh SHALL be idempotent: re-running on unchanged corpus SHALL produce the same `df` / `idf` values. The refresh SHALL NOT hold long-running locks on `transcript_chunks` (read-only scan + insert into freq table only).

#### Scenario: admin triggers IDF refresh for one show

- **WHEN** an admin POSTs to the IDF refresh endpoint with a `show_id`
- **THEN** the endpoint SHALL recompute token document-frequency over all `transcript_chunks` for that show
- **AND** upsert the result into `transcript_token_freq` (PK = (show_id, token))
- **AND** return the count of distinct tokens written along with the elapsed time

#### Scenario: refresh is idempotent

- **WHEN** the refresh endpoint is invoked twice consecutively on a show whose `transcript_chunks` did not change
- **THEN** the resulting `df` / `idf` values SHALL be identical
- **AND** the second invocation SHALL NOT raise an exception
