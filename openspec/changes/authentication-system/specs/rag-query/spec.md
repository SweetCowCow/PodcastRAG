## MODIFIED Requirements

### Requirement: Semantic search endpoint returns ranked chunks

The backend SHALL expose `POST /shows/{show_id}/query` which SHALL be guarded by `require_authenticated_user` and SHALL atomically decrement the caller's `quota_remaining` (incrementing `total_queries`) before invoking any embedding or LLM call. When called by an authenticated user with `quota_remaining > 0`, with `mode="search"` and a non-empty `question`, the endpoint SHALL embed the question, run pgvector cosine similarity search against `transcript_chunks` filtered to `completed` transcripts belonging to the specified show, and return the top 8 chunks ordered by ascending cosine distance. The response payload SHALL include the user's updated `quota_remaining` value.

#### Scenario: Search returns top-K chunks from the specified show

- **WHEN** an authenticated user with `quota_remaining > 0` calls `POST /shows/{show_id}/query` with body `{"question": "...", "mode": "search"}` and the show has at least 8 chunks from completed transcripts
- **THEN** the user's `quota_remaining` SHALL be decremented by 1 atomically before the embedding call
- **AND** the endpoint SHALL return HTTP 200 with a JSON body containing a `results` array of exactly 8 items (each with `episode_id`, `episode_title`, `start_time`, `end_time`, `text`, `distance`) ordered by ascending `distance`
- **AND** the response SHALL include the updated `quota_remaining`

#### Scenario: Search excludes other shows

- **WHEN** a search query is issued for `show_id=A` and a semantically closer chunk exists for `show_id=B`
- **THEN** the response SHALL NOT include any chunk whose owning episode belongs to `show_id=B`

#### Scenario: Search excludes incomplete transcripts

- **WHEN** a search query is issued and one episode in the show has a transcript whose `status` is not `completed`
- **THEN** the response SHALL NOT include any chunk from that incomplete transcript

#### Scenario: Unauthenticated request is rejected

- **WHEN** a request to `POST /shows/{show_id}/query` arrives with no valid session cookie
- **THEN** the response SHALL be HTTP 401 with error code `not_authenticated`
- **AND** no embedding API SHALL be called

#### Scenario: Quota-exhausted request is rejected before LLM call

- **WHEN** an authenticated user with `quota_remaining=0` sends a query request
- **THEN** the response SHALL be HTTP 429 with error code `quota_exhausted`
- **AND** no embedding or LLM API SHALL be called
- **AND** `total_queries` SHALL NOT be incremented
