## MODIFIED Requirements

### Requirement: Chat endpoint answers with citations using Tier 2 RAG

The backend SHALL expose `POST /shows/{show_id}/query` which, when called with `mode="chat"`, SHALL execute the Tier 2 RAG pipeline: (1) if the request includes a non-empty `messages` history, rewrite the question to a standalone form using the configured rewrite model; (2) embed the (rewritten) question; (3) retrieve top 8 chunks via pgvector; (4) generate an answer using the configured answer model with the retrieved chunks as grounding, requesting structured JSON output containing `answer` and `used_chunk_ids`; (5) return the answer together with only the citation chunks referenced in `used_chunk_ids`. If JSON parsing of the model output fails, the endpoint SHALL fall back to returning the raw text as `answer` with all retrieved chunks as `citations`.

#### Scenario: First turn skips rewrite

- **WHEN** a client calls chat mode with an empty or missing `messages` array
- **THEN** the endpoint SHALL NOT call the rewrite model, SHALL embed the original `question` directly, SHALL retrieve chunks, and SHALL return an answer from the answer model

#### Scenario: Follow-up turn uses rewritten question for retrieval

- **WHEN** a client calls chat mode with a non-empty `messages` history and a new `question` that contains a pronoun or implicit reference
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

## ADDED Requirements

### Requirement: Citation click navigates to transcript with highlight

The frontend ChatBubble citation badge SHALL be interactive. When a user clicks a citation badge, the application SHALL navigate to TranscriptPage for the cited episode and SHALL scroll to and visually highlight the transcript segment at the cited `start_time`. The highlight SHALL be applied as a background color accent for 3 seconds then fade out.

#### Scenario: Citation badge click navigates to transcript

- **WHEN** a user clicks a citation badge in a ChatBubble
- **THEN** the application SHALL navigate to TranscriptPage with `selectedEpisode.id` equal to the citation's `episode_id` and `highlightTime` equal to the citation's `start_time`

#### Scenario: Transcript highlights cited segment on load

- **WHEN** TranscriptPage mounts with a non-null `highlightTime`
- **THEN** the page SHALL scroll to the first segment whose `start_time` is closest to `highlightTime` and SHALL apply a 3-second highlighted background to that segment
