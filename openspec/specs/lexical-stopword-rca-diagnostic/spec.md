# lexical-stopword-rca-diagnostic Specification

## Purpose

TBD - created by archiving change 'lexical-stopword-filter-rca-deep-dive'. Update Purpose after archive.

## Requirements

### Requirement: RCA SHALL produce per-question lexical bridge audit for regress items

The diagnostic SHALL run `diff_baselines.py` against `baseline-post-judge-v2-2026-05-27.json` (pre-change) and `baseline-stopword-filter-2026-05-28-chat.json` (post-change), identify all items whose `chunk_recall_grouped` regressed or whose grading went PASS → FAIL, and for each such item produce a row containing: item id, GT chunk id(s), GT chunk text excerpt, old ts_query string, new ts_query string, `matches=true/false` for both queries against each GT chunk, `ts_rank` value for both queries.

#### Scenario: regress audit table is produced and persisted

- **WHEN** the RCA pipeline completes
- **THEN** the case study SHALL contain a section listing at least 5 audited regress items with the columns described above

---
### Requirement: RCA SHALL classify bridge tokens removed by the filter

For each regress item identified above, the diagnostic SHALL classify the tokens that were dropped by the stop-word filter and 1-char drop into three categories: (a) true stop-words with no signal value (safe to drop), (b) content-bearing tokens that were misclassified (e.g. common verbs like `想 / 說 / 用` that carry topical signal), (c) single-character signal tokens (e.g. `歌 / 酒 / 火 / 習` that are real query keywords). The diagnostic SHALL report aggregate counts for each category across all regress items.

#### Scenario: token classification table is produced

- **WHEN** the RCA pipeline completes the bridge audit
- **THEN** the case study SHALL contain a 3-row table reporting the count of dropped tokens per category and at least one concrete example token per category

---
### Requirement: RCA SHALL quantify RRF merge contribution from weak lexical match

The diagnostic SHALL measure the recall delta between two configurations: (1) hybrid retrieval where GT chunks have `matches=true` in lexical pool with low ts_rank (the pre-change state), (2) hybrid retrieval where GT chunks have `matches=false` (the post-change state). The measurement SHALL be expressed as the absolute and percentage difference in `chunk_recall_grouped` attributable to weak-lexical RRF contribution.

#### Scenario: RRF contribution magnitude is reported

- **WHEN** the RCA pipeline completes the RRF audit
- **THEN** the case study SHALL contain a quantitative statement of the form "Weak-lexical RRF contribution to chunk_recall is approximately X percentage points, equivalent to N items recovered" backed by per-item data

---
### Requirement: RCA SHALL produce at least two ranked follow-up change candidates

The case study SHALL end with a section listing at least two distinct follow-up change candidates, each named in kebab-case suitable for `spectra new change`, with: short proposal summary, expected effort (S/M/L), expected impact direction (chunk_recall delta estimate range), and ranking by ROI. Candidates SHALL be drawn from the four directions enumerated in the proposal but the diagnostic MAY add new candidates discovered during analysis.

#### Scenario: candidates are ranked

- **WHEN** the case study end section is rendered
- **THEN** it SHALL include at least two candidates ordered by ROI rank
- **AND** the top candidate SHALL be the diagnostic's recommendation for the next change to propose
