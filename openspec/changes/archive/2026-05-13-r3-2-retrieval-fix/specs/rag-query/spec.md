## ADDED Requirements

### Requirement: Description hit cap is tunable via `RAG_DESCRIPTION_CAP` env

The backend SHALL read `RAG_DESCRIPTION_CAP` at module import time. The value SHALL be an integer >= 0 and SHALL override the in-code `DESCRIPTION_CAP` constant used by `retrieve_hybrid` to bound the number of `source == "description"` hits in the top-K result. When `RAG_DESCRIPTION_CAP` is unset, malformed (non-integer), or negative, the in-code default SHALL be used and a single warning SHALL be logged to stderr describing the fallback. Changing this env variable SHALL require a service restart to take effect.

#### Scenario: env unset uses in-code default

- **GIVEN** `RAG_DESCRIPTION_CAP` is unset
- **WHEN** the backend imports `app.services.rag`
- **THEN** the runtime cap SHALL equal the in-code `DESCRIPTION_CAP` default
- **AND** no warning SHALL be logged

#### Scenario: env value 0 fully excludes description hits

- **GIVEN** `RAG_DESCRIPTION_CAP=0`
- **WHEN** `/shows/{show_id}/search` is invoked with a question that would normally produce description hits
- **THEN** the response top-K SHALL contain zero items with `source == "description"`

#### Scenario: malformed env falls back with warning

- **GIVEN** `RAG_DESCRIPTION_CAP=abc`
- **WHEN** the backend imports `app.services.rag`
- **THEN** the runtime cap SHALL equal the in-code default
- **AND** a single warning line SHALL be emitted on stderr naming both the malformed value and the fallback value

### Requirement: Show-name term filtering is tunable via `RAG_SHOW_NAME_FILTER` env

The backend SHALL read `RAG_SHOW_NAME_FILTER` at module import time. When the value (case-insensitive) is `"false"`, `"0"`, or `"off"`, the `_build_ts_query` lexical query builder SHALL NOT drop tokens listed in `tokenizer.get_show_name_terms()`. Any other value (or unset) SHALL preserve current strip behaviour. The semantic / embedding path SHALL be unaffected regardless of this flag. Changing this env variable SHALL require a service restart to take effect.

#### Scenario: env unset preserves current strip behaviour

- **GIVEN** `RAG_SHOW_NAME_FILTER` is unset
- **AND** `tokenizer.get_show_name_terms()` contains `"這又沒有很屌"`
- **WHEN** `_build_ts_query("節目名「這又沒有很屌」是怎麼來的？")` is called
- **THEN** the returned tsquery SHALL NOT contain `"這又沒有很屌"` as a term

#### Scenario: env set to false retains show-name tokens

- **GIVEN** `RAG_SHOW_NAME_FILTER=false`
- **AND** `tokenizer.get_show_name_terms()` contains `"這又沒有很屌"`
- **WHEN** `_build_ts_query("節目名「這又沒有很屌」是怎麼來的？")` is called
- **THEN** the returned tsquery SHALL contain `"這又沒有很屌"` as a term

#### Scenario: embedding side never affected

- **GIVEN** any value of `RAG_SHOW_NAME_FILTER`
- **WHEN** `/shows/{show_id}/search` embeds the question
- **THEN** the full question text (including any show-name term) SHALL be embedded; no token SHALL be stripped from the embedding input
