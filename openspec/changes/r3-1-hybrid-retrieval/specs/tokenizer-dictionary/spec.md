## ADDED Requirements

### Requirement: Tokeniser service exposes tokenize() backed by jieba + custom dictionary

The backend SHALL expose a `tokenize(text: str) -> list[str]` function in `backend/app/services/tokenizer.py` that returns jieba-segmented tokens of the input string. At process startup, the service SHALL query all rows of `tokenizer_custom_terms` and SHALL register each term with `jieba.add_word(term, weight)` so that custom terms are not split into single characters. The service SHALL be safe for re-initialisation: a `reload_dictionary()` function SHALL clear jieba's user-added words for the current process and re-register from the current DB state.

#### Scenario: Process startup loads dictionary

- **WHEN** a backend / worker / dispatcher / beat process starts
- **THEN** the tokenizer module SHALL run a one-time initialisation that loads all rows from `tokenizer_custom_terms` and calls `jieba.add_word(term, weight)` for each

#### Scenario: Custom term not split into chars

- **GIVEN** the row `term='迪拉胖', weight=100` exists in `tokenizer_custom_terms`
- **WHEN** `tokenize("迪拉胖很煩")` is called after startup loaded the dictionary
- **THEN** the output SHALL contain `"迪拉胖"` as a single token (and SHALL NOT contain `"迪"`, `"拉"`, `"胖"` separately)

#### Scenario: Tokenize ignores leading/trailing whitespace

- **WHEN** `tokenize("   迪拉胖很煩  ")` is called
- **THEN** the result SHALL be the same as `tokenize("迪拉胖很煩")` (the wrapper SHALL strip whitespace before invoking jieba)

### Requirement: Admin CRUD endpoints for tokenizer_custom_terms

The backend SHALL expose admin-gated REST endpoints (`require_admin`):

- `GET /admin/tokenizer/terms` — list all rows ordered by `created_at` DESC
- `POST /admin/tokenizer/terms` — body `{term: str, weight: int = 100}`; insert one row, `created_by_user_id` set to caller
- `DELETE /admin/tokenizer/terms/{id}` — delete one row by UUID
- `POST /admin/tokenizer/reload` — trigger `reload_dictionary()` in the local process and dispatch a Celery broadcast task to do the same on workers / beat / dispatcher

These endpoints SHALL require an authenticated admin (existing `require_admin` dependency). Anonymous and non-admin authenticated callers SHALL be rejected with HTTP 401 / 403 respectively.

#### Scenario: Admin lists current dictionary

- **GIVEN** 3 rows exist in `tokenizer_custom_terms`
- **WHEN** an admin calls `GET /admin/tokenizer/terms`
- **THEN** the response SHALL be HTTP 200 with a JSON array of length 3

#### Scenario: Admin adds a new term

- **WHEN** an admin calls `POST /admin/tokenizer/terms` with body `{"term": "顏色"}`
- **THEN** the response SHALL be HTTP 201 with the inserted row including its UUID
- **AND** subsequent `GET /admin/tokenizer/terms` SHALL include `"顏色"`

#### Scenario: Adding a duplicate term returns 409

- **GIVEN** `"台通"` already exists in the table
- **WHEN** an admin calls `POST /admin/tokenizer/terms` with body `{"term": "台通"}`
- **THEN** the response SHALL be HTTP 409 with `error_code='duplicate_term'`

#### Scenario: Admin reloads dictionary across all processes

- **WHEN** an admin calls `POST /admin/tokenizer/reload`
- **THEN** the local backend process SHALL re-query the table and re-register jieba terms within 5 seconds
- **AND** the response SHALL be HTTP 202 indicating the reload broadcast was dispatched

#### Scenario: Non-admin denied

- **WHEN** an authenticated non-admin user calls any `/admin/tokenizer/*` endpoint
- **THEN** the response SHALL be HTTP 403 with `error_code='forbidden'`

### Requirement: Seed dictionary builder script

The repository SHALL contain `backend/scripts/build_jieba_seed_dict.py`, a CLI tool that scans transcripts for high-frequency multi-character entity candidates that jieba's default tokeniser splits into single characters. It SHALL output a CSV (`docs/jieba_seed_candidates.csv`) with columns `[term, occurrences, sample_episode_titles]` for human review. The CSV is then manually curated, and the curated subset is loaded into `tokenizer_custom_terms` via a separate import command (`python -m backend.scripts.import_jieba_seed --csv <path>`).

#### Scenario: Script outputs CSV ordered by frequency

- **WHEN** the build script runs against a corpus of 354 transcripts
- **THEN** it SHALL produce a CSV containing candidate terms ordered by descending occurrence count
- **AND** each row SHALL include the term, its total occurrence count, and up to 3 sample episode titles where it appears

#### Scenario: Import command persists curated terms with seed_script source

- **WHEN** the import command runs against a curated CSV with 70 rows
- **THEN** 70 rows SHALL be inserted into `tokenizer_custom_terms` with `source='seed_script'`
- **AND** any row whose term already exists SHALL be skipped (logged at INFO level), not failing the whole import
