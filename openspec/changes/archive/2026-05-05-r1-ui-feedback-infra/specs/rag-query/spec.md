## ADDED Requirements

### Requirement: RAG query response includes stable query_id

The `POST /query` endpoint SHALL include a `query_id` field (opaque string, max 64 chars, unique per response) in its JSON response. The frontend SHALL use this `query_id` when posting to `/qa-feedback` and `/events` so server-side rows can be correlated with the originating answer. The `query_id` SHALL be generated server-side (not by the client) and SHALL be present on all successful query responses regardless of whether RAG returned answers.

#### Scenario: Successful query response includes query_id

- **WHEN** a logged-in user calls `POST /query` with a valid question
- **THEN** the JSON response SHALL contain a non-empty `query_id` string

#### Scenario: query_id values are unique across responses

- **GIVEN** the same user issues two consecutive `POST /query` requests with the same body
- **THEN** the two responses SHALL contain different `query_id` values
