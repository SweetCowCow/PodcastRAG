## ADDED Requirements

### Requirement: Q1 chunk presence query SHALL be executed before any chunking or retrieval code change

The diagnostic protocol SHALL begin by running a read-only SQL query against the prod database to enumerate `transcript_chunks` rows for episode `c1d87278-7dba-4fb1-930d-c2bd3a3461d2` with `start_time BETWEEN 1700 AND 2080`. The query MUST be executed via backend container exec with `PGPASSWORD` supplied through environment variables (never via argv or URL). The Q1 result determines the next branch: empty range (no chunk row whose start_time falls inside `[1780, 1820]`) routes to Q2 for root cause A confirmation; non-empty range routes to Q3 for root cause B confirmation.

#### Scenario: Q1 returns gap covering 1780-1820

- **WHEN** Q1 executes and the returned rows show no chunk with `start_time` inside `[1780, 1820]`
- **THEN** the diagnostic SHALL record root cause A (chunking boundary) as the working hypothesis and proceed to Q2

##### Example: gap confirmed

- **GIVEN** Q1 returns rows at `start_time` 1678.58, 1719.78, 2074.76 (matching b23 case study evidence)
- **WHEN** the diagnostic checks for any row with `start_time` between 1780 and 1820
- **THEN** zero rows match and root cause A branch is selected

#### Scenario: Q1 returns chunk covering 1790 or 1808

- **WHEN** Q1 returns at least one chunk row whose `[start_time, end_time]` interval overlaps 1790.18 or 1808.78
- **THEN** the diagnostic SHALL record root cause B (retrieve filter) as the working hypothesis and proceed to Q3

### Requirement: Q2 segment presence query SHALL verify whether transcript_segments exist in the gap when root cause A is suspected

When Q1 routes to root cause A, the diagnostic SHALL execute a read-only SQL query against `transcript_segments` for the same transcript with `start_time BETWEEN 1780 AND 1820`. Q2 distinguishes two sub-cases: (A1) segments exist but chunking aggregation merged them into adjacent chunks, versus (A2) segments themselves are missing from the database. Q2 results SHALL be reported in the case study with row counts and concrete segment IDs.

#### Scenario: segments exist (A1 — chunking aggregation gap)

- **WHEN** Q2 returns one or more `transcript_segments` rows in `[1780, 1820]`
- **THEN** the diagnostic SHALL classify the root cause as A1 and the fix direction MUST target the chunking aggregation rule (paragraph boundary, max chunk length, or speaker turn merging)

#### Scenario: segments missing (A2 — upstream transcription gap)

- **WHEN** Q2 returns zero `transcript_segments` rows in `[1780, 1820]`
- **THEN** the diagnostic SHALL classify the root cause as A2 and the fix direction MUST target the upstream transcription pipeline (Whisper segmentation, post-processing, or ASR filtering)

### Requirement: Q3 RRF reproduction query SHALL identify the filter responsible when root cause B is suspected

When Q1 routes to root cause B, the diagnostic SHALL reproduce the `_TRANSCRIPT_RRF_SQL` pipeline locally against the chunks Q1 returned that overlap 1790 or 1808. The reproduction MUST capture each chunk's semantic rank, lexical rank, RRF score, and whether it passed the `text_tsvector @@ to_tsquery('simple', :ts_query)` lexical predicate. Q3 SHALL identify the specific filter clause or threshold that excluded the chunk.

#### Scenario: lexical predicate excludes chunk

- **WHEN** Q3 shows the chunk's `text_tsvector @@ to_tsquery('simple', :ts_query)` evaluates to false for the b20 query
- **THEN** the diagnostic SHALL classify the root cause as B-lexical and the fix direction MUST target lexical tokenization (jieba dictionary, query expansion, or fallback to semantic-only)

#### Scenario: chunk ranks beyond per-side cap

- **WHEN** Q3 shows the chunk passes the lexical predicate but its `rank_s` or `rank_l` exceeds `RRF_PER_SIDE` (50)
- **THEN** the diagnostic SHALL classify the root cause as B-cap and the fix direction MUST target widening `RRF_PER_SIDE` or adding a per-episode reservation

### Requirement: Case study output SHALL document evidence, root cause, and fix direction without proposing code changes

The diagnostic SHALL emit one Markdown file at `docs/case-studies/chunk-level-retrieval-rca-b20-2026-05-27.md` containing: (1) the three SQL queries verbatim with parameters, (2) the row-level results for each query that ran, (3) the explicit root cause classification (A1, A2, B-lexical, or B-cap), (4) a one-paragraph fix direction naming the next change to propose, and (5) explicit non-actions list confirming no prod code, eval baseline, or dataset was modified. The case study MUST NOT contain code patches or implementation snippets for the fix itself.

#### Scenario: case study satisfies completeness check

- **WHEN** the case study is finalized
- **THEN** the file SHALL contain a "Root cause" section naming exactly one of {A1, A2, B-lexical, B-cap, inconclusive}, and a "Next change recommendation" section naming the proposed follow-up change name (e.g., `chunking-boundary-fix-ep134-style` or `retrieve-hybrid-filter-relax`)

#### Scenario: inconclusive result is allowed

- **WHEN** Q1/Q2/Q3 results do not cleanly map to any of A1/A2/B-lexical/B-cap (e.g., chunks exist and pass all filters but still rank below `LIMIT :k`)
- **THEN** the case study SHALL record "inconclusive" with a documented hypothesis for the next diagnostic step, and the change can still archive without forcing a premature root cause label

### Requirement: Diagnostic execution SHALL NOT modify prod data, prod code, or eval baselines

All SQL queries in the protocol MUST be read-only (SELECT only, no DDL, no DML). No deployment, no environment variable change, no code commit, and no eval baseline rerun SHALL be performed as part of this change. The diagnostic MUST NOT call APIs that mutate state (e.g., admin transcription kickoff, chunk regeneration).

#### Scenario: read-only enforcement

- **WHEN** any task in this change attempts to run a non-SELECT SQL statement, deploy code, or modify environment variables
- **THEN** the task SHALL be rejected and the diagnostic SHALL fail with a documented violation rather than proceeding
