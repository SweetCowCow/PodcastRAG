## ADDED Requirements

### Requirement: OpenAI provider records api-health events

The `OpenAIWhisperProvider` SHALL, for every outbound call to `audio.transcriptions.create` (both the single-request path and each chunk iteration in the oversized path), measure the call duration and emit one event to the `api_health` tracker under the api name `openai_whisper`, reporting success or failure, the measured duration, and — on failure — a stable error category produced by the `api_health` error classifier.

The tracker call SHALL occur regardless of whether the upstream call succeeded or raised, and SHALL NOT swallow the original exception. A tracker failure (e.g. Redis down) SHALL NOT alter the behaviour observed by the rest of the transcription pipeline.

Any other component that invokes external APIs currently covered by the tracker (OpenAI Chat for answer/rewrite; OpenAI Embedding for RAG chunking) SHALL likewise emit one event per call under the api names `openai_chat` and `openai_embedding` respectively.

#### Scenario: Successful Whisper call emits ok event

- **WHEN** a single-request Whisper call completes successfully in 850 ms
- **THEN** exactly one `api_health.record("openai_whisper", ok=True, duration_ms=850, error_category=None, http_status=200)` invocation SHALL be made after the API returns, before the provider returns its result
- **AND** the provider SHALL return the `TranscriptionResult` exactly as it would without the tracker

#### Scenario: Failed Whisper call emits categorised event and re-raises

- **WHEN** a Whisper call raises `openai.RateLimitError` with an `insufficient_quota` code after 120 ms
- **THEN** `api_health.record("openai_whisper", ok=False, duration_ms=120, error_category="quota_exceeded", http_status=429)` SHALL be invoked
- **AND** the original `openai.RateLimitError` SHALL propagate out of the provider unchanged

#### Scenario: Chunked path emits one event per chunk

- **WHEN** the provider processes an oversized audio that results in 3 chunk uploads where the second chunk fails with a 503 server error
- **THEN** exactly 3 `api_health.record` invocations SHALL occur under `openai_whisper` — one `ok=True` for chunk 1, one `ok=False, error_category="server_error", http_status=503` for chunk 2, and none for chunk 3 (since processing stops on chunk 2's raise)

#### Scenario: Tracker failure does not affect pipeline

- **WHEN** `api_health.record` raises `redis.ConnectionError` and the upstream API returned successfully
- **THEN** the provider SHALL still return the `TranscriptionResult` to its caller
- **AND** no exception SHALL propagate from the tracker failure
