## ADDED Requirements

### Requirement: Query endpoint maps OpenAI exceptions to friendly error responses

The backend SHALL catch OpenAI client exceptions raised during embedding, rewrite, or answer calls within `POST /shows/{show_id}/query` and convert each to an `HTTPException` whose body matches the unified error response schema. The mapping SHALL be:

- `openai.RateLimitError` whose error body code equals `"insufficient_quota"` SHALL produce HTTP 429 with `error_code = "llm_quota_exceeded"`.
- `openai.RateLimitError` for any other reason SHALL produce HTTP 429 with `error_code = "llm_rate_limited"`.
- `openai.AuthenticationError` SHALL produce HTTP 502 with `error_code = "llm_auth_failed"`.
- `openai.APIConnectionError` and `openai.APITimeoutError` SHALL produce HTTP 503 with `error_code = "llm_unavailable"`.

The `provider` field of the error response SHALL be derived from the call site: requests that go through the embeddings service SHALL set `provider = "OpenAI"` (since embeddings always target the official OpenAI endpoint); chat and rewrite requests SHALL set `provider` to the value returned by `infer_provider_label` applied to the configured `answer_base_url` or `rewrite_base_url`.

#### Scenario: Embeddings rate limit returns 429 with quota_exceeded

- **WHEN** the embeddings service raises `openai.RateLimitError` with body `{"error": {"code": "insufficient_quota"}}` during a query request
- **THEN** the endpoint SHALL respond HTTP 429 with body `{"detail": {"error_code": "llm_quota_exceeded", "provider": "OpenAI", "detail": <message>}}`

#### Scenario: Chat rate limit identifies Zeabur AI Hub provider

- **WHEN** the answer model is configured with `answer_base_url` containing `"zeabur"` and the chat call raises `openai.RateLimitError` not matching `insufficient_quota`
- **THEN** the endpoint SHALL respond HTTP 429 with `provider = "Zeabur AI Hub"` and `error_code = "llm_rate_limited"`

#### Scenario: Authentication error returns 502

- **WHEN** any OpenAI client call within the query endpoint raises `openai.AuthenticationError`
- **THEN** the endpoint SHALL respond HTTP 502 with `error_code = "llm_auth_failed"` and the appropriate `provider` label

#### Scenario: Connection error returns 503

- **WHEN** any OpenAI client call within the query endpoint raises `openai.APIConnectionError` or `openai.APITimeoutError`
- **THEN** the endpoint SHALL respond HTTP 503 with `error_code = "llm_unavailable"` and the appropriate `provider` label

#### Scenario: api_health record is preserved across the conversion

- **WHEN** the embeddings or chat service raises an OpenAI exception that the endpoint converts to an `HTTPException`
- **THEN** the underlying service SHALL still record one event via `api_health.record` for the failed call, and the endpoint SHALL NOT emit a duplicate record

### Requirement: Provider label is inferred from base URL

The backend SHALL provide a function `infer_provider_label(base_url: str | None) -> str` in the LLM configuration module that returns a human-readable label identifying the provider. The function SHALL return `"OpenAI"` when `base_url` is `None` or its hostname ends with `openai.com`, `"Zeabur AI Hub"` when the hostname contains `zeabur`, and the URL hostname (or `"External API"` when the hostname cannot be parsed) otherwise.

#### Scenario: None base_url returns OpenAI

- **WHEN** `infer_provider_label(None)` is called
- **THEN** the function SHALL return `"OpenAI"`

#### Scenario: Official OpenAI base URL returns OpenAI

- **WHEN** `infer_provider_label("https://api.openai.com/v1")` is called
- **THEN** the function SHALL return `"OpenAI"`

#### Scenario: Zeabur AI Hub base URL returns Zeabur AI Hub

- **WHEN** `infer_provider_label("https://aihub-xyz.zeabur.app/v1")` is called
- **THEN** the function SHALL return `"Zeabur AI Hub"`

#### Scenario: Unknown provider falls back to hostname

- **WHEN** `infer_provider_label("https://api.together.xyz/v1")` is called
- **THEN** the function SHALL return `"api.together.xyz"`
