## ADDED Requirements

### Requirement: Show-name tokens excluded from lexical query

`_build_ts_query(question)` in `backend/app/services/rag.py` SHALL load the set of `term` values from `tokenizer_custom_terms` where `is_show_name = true` and SHALL drop those tokens from the OR-joined `to_tsquery` string after jieba tokenisation. The exclusion SHALL apply only to the lexical (tsvector) side of hybrid retrieval; semantic embedding SHALL be computed against the original full question text unchanged.

The set of show-name tokens SHALL be cached in process memory and refreshed when `reload_dictionary()` is invoked (so admins can toggle the flag and reload to take effect across services).

#### Scenario: Show-name token dropped from ts_query

- **GIVEN** `tokenizer_custom_terms` contains `('這又沒有很屌', is_show_name=true)`
- **WHEN** `_build_ts_query("這又沒有很屌的節目名怎麼來的")` is called after dict load
- **THEN** the returned tsquery string SHALL NOT contain `這又沒有很屌`
- **AND** SHALL still contain `節目名` and `怎麼` (other multi-char tokens)

#### Scenario: Reload picks up flag changes

- **GIVEN** a row with `is_show_name=false` was loaded at startup
- **WHEN** an admin calls `POST /admin/tokenizer/terms/{id}` (or equivalent UPDATE) to set it to `true`
- **AND** then calls `POST /admin/tokenizer/reload`
- **THEN** subsequent `_build_ts_query` calls SHALL drop that token

#### Scenario: Embedding side unaffected

- **WHEN** a query containing a show-name token is embedded
- **THEN** the full question text (including the show-name token) SHALL be passed to the embedding model

### Requirement: Single-character token filter removed

The `_build_ts_query` function SHALL accept jieba tokens of any length ≥ 1 (no length-2 minimum). Token filtering SHALL be limited to: (a) whitespace-only tokens, (b) pure-punctuation tokens, (c) tokens dropped per the show-name exclusion above.

#### Scenario: Length-1 tokens accepted

- **GIVEN** a query that yields jieba tokens including single-character entries
- **WHEN** `_build_ts_query` runs
- **THEN** the returned tsquery string SHALL include those length-1 tokens (e.g. `是`, `了`)

(Rationale: R3.1 v3/v4 eval bake-off proved length-1 filtering had zero impact on episode-level recall (v1=v3, v2=v4 across 48 items). Removing it simplifies the code path. The OR-join with `ts_rank` weighting already suppresses common-particle noise.)

## MODIFIED Requirements

### Requirement: Admin CRUD endpoints for tokenizer_custom_terms

The backend SHALL expose admin-gated REST endpoints (`require_admin`):

- `GET /admin/tokenizer/terms` — list all rows ordered by `created_at` DESC, **including the `is_show_name` boolean per row**
- `POST /admin/tokenizer/terms` — body `{term: str, weight: int = 100, is_show_name: bool = false}`; insert one row, `created_by_user_id` set to caller
- `PATCH /admin/tokenizer/terms/{id}` — body `{is_show_name: bool}`; update the show-name flag without touching other fields
- `DELETE /admin/tokenizer/terms/{id}` — delete one row by UUID
- `POST /admin/tokenizer/reload` — trigger `reload_dictionary()` in the local process and dispatch a Celery broadcast task to do the same on workers / beat / dispatcher

These endpoints SHALL require an authenticated admin (existing `require_admin` dependency). Anonymous and non-admin authenticated callers SHALL be rejected with HTTP 401 / 403 respectively.

#### Scenario: List includes is_show_name

- **GIVEN** 3 rows exist where one has `is_show_name=true`
- **WHEN** an admin calls `GET /admin/tokenizer/terms`
- **THEN** each item SHALL include `is_show_name` (boolean)
- **AND** the row with `is_show_name=true` SHALL reflect that

#### Scenario: PATCH toggles flag

- **GIVEN** a row currently has `is_show_name=false`
- **WHEN** an admin calls `PATCH /admin/tokenizer/terms/{id}` with body `{"is_show_name": true}`
- **THEN** the response SHALL be HTTP 200 with the updated row
- **AND** subsequent `GET` SHALL show `is_show_name=true`

#### Scenario: Create with is_show_name

- **WHEN** an admin posts `{"term": "大嘻哈時代", "is_show_name": true}`
- **THEN** the inserted row SHALL have `is_show_name=true`

#### Scenario: Adding a duplicate term returns 409

- **GIVEN** `"台通"` already exists
- **WHEN** an admin calls `POST` with the same `term`
- **THEN** the response SHALL be HTTP 409 with `error_code='duplicate_term'`

#### Scenario: Admin reloads dictionary across all processes

- **WHEN** an admin calls `POST /admin/tokenizer/reload`
- **THEN** the local backend process SHALL re-query the table and re-register jieba terms within 5 seconds
- **AND** the response SHALL be HTTP 202

#### Scenario: Non-admin denied

- **WHEN** an authenticated non-admin user calls any `/admin/tokenizer/*` endpoint
- **THEN** the response SHALL be HTTP 403
