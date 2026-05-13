## ADDED Requirements

### Requirement: Two-layer episode routing SHALL be disabled by default

The retrieval pipeline (`backend/app/services/rag.py`) SHALL NOT apply two-layer episode routing by default. The `_should_skip_routing()` predicate SHALL return `True` whenever the `ENABLE_TWO_LAYER_ROUTING` environment variable is unset, empty, or equal to any case-insensitive form of `"false"`. The legacy routing pass MAY be re-enabled for diagnostics by setting `ENABLE_TWO_LAYER_ROUTING=true`. The hybrid retrieval (RRF over `transcript_chunks` and `episode_description_chunks` filtered by `show_id`) SHALL operate over the full show without a pre-filter to a routed subset of `episode_id` values.

#### Scenario: No env var set yields full-show retrieval

- **GIVEN** `ENABLE_TWO_LAYER_ROUTING` is not set in the backend process environment
- **WHEN** a caller invokes `POST /shows/{show_id}/search` with any valid `question`
- **THEN** `_should_skip_routing(question)` SHALL return `True`
- **AND** `retrieve_hybrid` SHALL be invoked with `episode_id_filter=None`
- **AND** the returned chunks SHALL be drawn from the full set of `transcript_chunks` and `episode_description_chunks` belonging to the show (subject only to the RRF top-K cutoff)

#### Scenario: Env var set to "true" re-enables routing for diagnostics

- **GIVEN** `ENABLE_TWO_LAYER_ROUTING=true` is set in the backend process environment
- **WHEN** a caller invokes `POST /shows/{show_id}/search` with a question whose jieba tokenisation yields at least 2 multi-character tokens
- **THEN** `_should_skip_routing(question)` SHALL return `False`
- **AND** the retrieval pipeline SHALL invoke `route_episodes` to obtain a top-K episode list
- **AND** `retrieve_hybrid` SHALL be invoked with `episode_id_filter` set to that list

#### Scenario: Env var "false" is functionally equivalent to unset

- **GIVEN** `ENABLE_TWO_LAYER_ROUTING=false` is set in the backend process environment
- **WHEN** a caller invokes `POST /shows/{show_id}/search`
- **THEN** `_should_skip_routing(question)` SHALL return `True`
- **AND** retrieval SHALL behave identically to the unset case
