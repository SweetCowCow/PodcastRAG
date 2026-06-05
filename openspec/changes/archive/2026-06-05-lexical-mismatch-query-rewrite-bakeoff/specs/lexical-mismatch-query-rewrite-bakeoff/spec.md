## ADDED Requirements

### Requirement: Bake-off compares a fixed set of query-rewrite arms

The bake-off SHALL evaluate exactly four arms against the same downstream retrieve path, holding every variable constant except how the query is rewritten before retrieval: `control` (unmodified query), `query-expansion`, `hyde`, and `multi-vector`. All arms SHALL share the same candidate-pool settings and the same chunk corpus.

#### Scenario: All arms run the identical downstream retrieve

- **WHEN** the bake-off runner executes a case across the four arms
- **THEN** each arm SHALL produce only its rewritten `(lexical_query, embedding_vectors)` and feed them into the same shared retrieve function
- **AND** no arm SHALL alter candidate-pool size, chunk corpus, or rerank configuration

### Requirement: Fixed test cases with calibration regression guard

The bake-off SHALL run a fixed case set comprising the human-verified targets b20 (must chunks @1719, @1993) and b23 (must chunks @1766, @1819, @1847, @1866), plus a calibration regression set of queries that `control` already retrieves correctly. The calibration set SHALL be used to detect whether any non-control arm degrades previously-correct retrieval.

#### Scenario: Calibration set flags a regressing arm

- **GIVEN** a query in the calibration set whose must chunks `control` retrieves
- **WHEN** a non-control arm fails to retrieve those must chunks for that query
- **THEN** the report SHALL mark that arm as regressing on calibration

### Requirement: Metrics are prefilter-rank, chunk_recall@must, and cost

For every (arm, case) pair the bake-off SHALL record the target chunk's prefilter-rank as the primary metric, chunk_recall over must chunks as the secondary metric, and cost (extra LLM call count and average latency) alongside both.

#### Scenario: Each cell carries all three metric groups

- **WHEN** the runner completes a (arm, case) measurement
- **THEN** the result record SHALL contain prefilter-rank, chunk_recall@must, extra-LLM-call-count, and average-latency for that cell

##### Example: b20 control cell

- **GIVEN** arm `control` on case b20
- **WHEN** measured
- **THEN** the cell records prefilter-rank for @1719 and @1993, chunk_recall@must, 0 extra LLM calls, and the control latency

### Requirement: Bake-off runs offline and read-only

The bake-off SHALL perform read-only retrieval measurement against the target backend and SHALL NOT write to any table or route through the online query API. When the target is prod, the runner SHALL verify session validity (authenticated `/me` returning 200) before measuring, and SHALL abort loudly on connection or auth failure rather than emit a partial report.

#### Scenario: Aborts on failed prod session

- **WHEN** the target backend is prod and the session check does not return 200
- **THEN** the runner SHALL abort with a surfaced error
- **AND** SHALL NOT produce a results file or report

### Requirement: Report contract

The bake-off SHALL emit a machine-readable JSON result set and a human-readable markdown report. The report SHALL contain every (arm, case) cell with no placeholders, a winner determination backed by the quantitative metrics, a calibration non-regression verdict for each non-control arm, a scoring-perspective section distinguishing quantitative arm ranking from human landing judgment, and a small-sample limitation disclaimer.

#### Scenario: A measurement error does not blank the report

- **GIVEN** one (arm, case) measurement raises an error
- **WHEN** the runner finishes
- **THEN** that cell SHALL be marked `ERROR`
- **AND** all other cells SHALL still be measured and reported

### Requirement: Stop-the-line before landing a winner

The bake-off SHALL NOT merge any arm into the prod retrieve path. After the report is produced the workflow SHALL stop and await an explicit human decision on whether to land a winner and which subsequent change lands it.

#### Scenario: Winner is reported but not landed

- **WHEN** the bake-off identifies a winning arm
- **THEN** the prod retrieve path SHALL remain unchanged
- **AND** the report SHALL record the winner as a recommendation pending human approval
