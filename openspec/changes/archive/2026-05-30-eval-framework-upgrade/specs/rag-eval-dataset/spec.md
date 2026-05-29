## ADDED Requirements

### Requirement: A `_calibration_8` dataset SHALL exist for prompt fingerprint diff use

The repository SHALL ship a small calibration golden set at `backend/eval/datasets/_calibration_8.json` containing 8 items selected from `extended-multi-turn-40.json` to cover representative `design_type` values: `show_overview`, `guest_find`, `topic_find`, `date_find`, `deep_dive` (with EP-ref), `cross_episode`, `multi_turn`, and `negative`. The file SHALL be a strict subset of the parent dataset (same item shape, no edits) and SHALL be regenerable via a documented selection rule.

#### Scenario: calibration set covers design type spectrum

- **WHEN** an operator opens `_calibration_8.json`
- **THEN** the file SHALL contain exactly 8 items
- **AND** each `design_type` value among the eight items SHALL appear at most twice (allowing one design_type to repeat if multi_turn is treated as its own type)
- **AND** each item SHALL be a verbatim copy of the corresponding item in `extended-multi-turn-40.json`

### Requirement: Calibration set SHALL be documented as the prompt fingerprint diff input

The dataset README (or accompanying inventory doc) SHALL document the calibration set's purpose: prompt change PRs run `prompt_fingerprint_diff.py` against this set to detect retrieval-side fingerprint drift before merging. The documentation SHALL state that the full 34-item golden set is NOT the input (too expensive per PR) and SHALL warn against using `_calibration_8` for any other measurement purpose.

#### Scenario: dataset README mentions calibration set purpose

- **WHEN** an operator opens `backend/eval/datasets/README.md`
- **THEN** the file SHALL include a section describing `_calibration_8.json` and its prompt fingerprint diff use case
- **AND** the section SHALL state the 8-item-not-34-item rationale (per-PR cost)
