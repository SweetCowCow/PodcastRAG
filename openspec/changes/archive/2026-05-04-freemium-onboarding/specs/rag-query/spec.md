## MODIFIED Requirements

### Requirement: Semantic search endpoint returns ranked chunks

The backend SHALL expose `POST /shows/{show_id}/search` which SHALL be guarded by the `optional_auth_with_ip_limit` dependency (see auth-system + ip-rate-limit capabilities). The endpoint accepts body `{"question": "<non-empty string>", "k": <optional int 1-50, default 8>}`. The endpoint SHALL embed the question using the configured embedding step, run pgvector cosine similarity search against `transcript_chunks` filtered to `completed` transcripts belonging to the specified show, and return the top-K chunks ordered by ascending cosine distance. The response SHALL NOT include any LLM-generated answer. The endpoint SHALL NOT decrement `quota_remaining` even for authenticated callers — the cost being controlled is the embedding API call only, and the IP rate limit (for anonymous) plus quota gating on the chat endpoint (for authenticated) are sufficient.

#### Scenario: Anonymous request under rate limit returns top-K chunks

- **GIVEN** an unauthenticated visitor whose IP counter is 5 and `ip_search_rate_limit_per_day=20`
- **WHEN** the visitor calls `POST /shows/{show_id}/search` with body `{"question": "歌單"}`
- **THEN** the IP counter SHALL become 6
- **AND** the embedding API SHALL be called once
- **AND** the response SHALL be HTTP 200 with up to 8 ranked chunks (default k)
- **AND** the response SHALL NOT contain an `answer` field

#### Scenario: Anonymous request over rate limit is rejected without embedding call

- **GIVEN** an unauthenticated visitor whose IP counter is at the limit
- **WHEN** the visitor calls `POST /shows/{show_id}/search`
- **THEN** the response SHALL be HTTP 429 with `error_code='ip_rate_limited'`
- **AND** no embedding API call SHALL be made

#### Scenario: Authenticated request bypasses IP limit

- **GIVEN** an authenticated user from an IP whose counter is at the daily limit
- **WHEN** the user calls `POST /shows/{show_id}/search`
- **THEN** the request SHALL be processed
- **AND** the IP counter SHALL NOT be incremented
- **AND** the response SHALL be HTTP 200 with ranked chunks
- **AND** the user's `quota_remaining` SHALL NOT be decremented

#### Scenario: Search excludes other shows

- **WHEN** a search query is issued for `show_id=A` and a semantically closer chunk exists for `show_id=B`
- **THEN** the response SHALL NOT include any chunk whose owning episode belongs to `show_id=B`

#### Scenario: Search excludes incomplete transcripts

- **WHEN** a search query is issued and one episode in the show has a transcript whose `status` is not `completed`
- **THEN** the response SHALL NOT include any chunk from that incomplete transcript

#### Scenario: k parameter is clamped

- **WHEN** the body has `{"k": 100}`
- **THEN** the response SHALL contain at most 50 chunks (the documented upper bound)

### Requirement: Chat endpoint answers with citations using Tier 2 RAG

The backend SHALL expose `POST /shows/{show_id}/query` guarded by `require_authenticated_user` and atomic quota decrement (see user-quota). The endpoint SHALL execute the Tier 2 RAG pipeline: (1) if the request includes a non-empty `messages` history, rewrite the question to a standalone form using the configured rewrite model; (2) embed the (rewritten) question; (3) retrieve top 8 chunks via pgvector; (4) generate an answer using the configured answer model with the retrieved chunks as grounding, requesting structured JSON output containing `answer` and `used_chunk_ids`; (5) return the answer together with only the citation chunks referenced in `used_chunk_ids`. If JSON parsing of the model output fails, the endpoint SHALL fall back to returning the raw text as `answer` with all retrieved chunks as `citations`. This endpoint SHALL NOT accept anonymous callers and SHALL NOT consult the IP rate limit (the auth + quota gates are the cost control).

#### Scenario: First turn skips rewrite

- **WHEN** a client calls `POST /shows/{show_id}/query` with an empty or missing `messages` array
- **THEN** the endpoint SHALL NOT call the rewrite model, SHALL embed the original `question` directly, SHALL retrieve chunks, and SHALL return an answer from the answer model

#### Scenario: Follow-up turn uses rewritten question for retrieval

- **WHEN** a client calls with a non-empty `messages` history and a new `question` that contains a pronoun or implicit reference
- **THEN** the endpoint SHALL call the rewrite model with the history and the new question, SHALL use the rewrite model's output as the retrieval query, and the answer model SHALL receive the original user messages plus the new question (not the rewritten form) as its conversation input

#### Scenario: Response includes only used citations

- **WHEN** chat mode completes successfully and the model returns valid JSON with `used_chunk_ids`
- **THEN** the response body SHALL contain `answer` (string) and `citations` (array containing only the chunks whose `ep:<episode_id>@<start_time>` key appears in `used_chunk_ids`), where `citations` length SHALL be less than or equal to the number of retrieved chunks

#### Scenario: Structured output parse failure falls back to full citations

- **WHEN** the answer model returns output that cannot be parsed as JSON or lacks the `answer` key
- **THEN** the endpoint SHALL treat the entire model output as the `answer` string and SHALL return all retrieved chunks as `citations`

#### Scenario: Sliding window limit enforced

- **WHEN** a client sends a `messages` array longer than 10 entries (5 user + 5 assistant)
- **THEN** the endpoint SHALL use only the most recent 10 entries when building prompts for both rewrite and answer models

#### Scenario: Anonymous request rejected with 401

- **WHEN** an unauthenticated request reaches `POST /shows/{show_id}/query`
- **THEN** the response SHALL be HTTP 401 with `error_code='not_authenticated'`
- **AND** no embedding or LLM API SHALL be called
