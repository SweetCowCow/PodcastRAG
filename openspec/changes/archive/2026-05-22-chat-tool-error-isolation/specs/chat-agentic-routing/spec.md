## ADDED Requirements

### Requirement: Agent tool dispatcher SHALL isolate tool errors via SAVEPOINT and return structured error envelope

The agent tool dispatcher (`backend/app/services/chat_agent/tools.py::_dispatch_tool`) SHALL wrap every tool callable invocation in a SQLAlchemy nested transaction (`begin_nested()` → PostgreSQL SAVEPOINT). When the tool callable raises any exception, the SAVEPOINT SHALL be rolled back automatically so the outer `AsyncSession` retains a clean transaction; subsequent tool calls in the same agent loop SHALL be able to execute database queries without encountering `InFailedSQLTransactionError`.

When a tool callable raises, the dispatcher SHALL convert the exception into a structured **Tool error envelope** with shape `{"ok": false, "kind": "validation" | "schema" | "transient" | "not_found" | "unknown", "internal_message": "<ExceptionClass>: <msg>", "user_hint": "<friendly zh-TW text>"}`. A helper `_classify_exception(exc)` SHALL classify the exception into one of those five `kind` values using a dispatch table:

- `pydantic.ValidationError` → `validation`
- `sqlalchemy.exc.ProgrammingError`, `IntegrityError`, `DataError` → `schema`
- `asyncio.TimeoutError`, `asyncpg.PostgresConnectionError`, `OperationalError` → `transient`
- `LookupError` (or future project `NotFoundError`) → `not_found`
- anything else → `unknown`

The dispatcher SHALL NOT return the legacy `{"error": "..."}` shape on failure — every failure path returns the envelope. Existing successful tool results SHALL remain unchanged (no `ok: true` wrapping required).

#### Scenario: Tool raises ProgrammingError, next tool still works

- **GIVEN** an agent loop where the first tool callable raises `ProgrammingError`
- **WHEN** `_dispatch_tool` returns the envelope and the agent loop proceeds to a second tool callable that issues a SELECT on the same `AsyncSession`
- **THEN** the second tool's query SHALL execute successfully (no `InFailedSQLTransactionError`)
- **AND** the first tool's `ToolCallTrace.raised` SHALL be the exception class name (e.g. `"ProgrammingError"`)
- **AND** the first tool's result dict SHALL contain keys `ok`, `kind`, `internal_message`, `user_hint`

#### Scenario: Schema error classified and user_hint sanitised

- **GIVEN** a tool callable raises `sqlalchemy.exc.ProgrammingError("column ts.start_seconds does not exist")`
- **WHEN** `_dispatch_tool` catches the exception
- **THEN** the returned envelope SHALL have `kind == "schema"`
- **AND** the envelope's `internal_message` SHALL contain `"ProgrammingError"` and the column reference
- **AND** the envelope's `user_hint` SHALL NOT contain `"ProgrammingError"`, the column name, or the word "transaction"

#### Scenario: Validation error classified

- **GIVEN** a tool is invoked with arguments that fail Pydantic schema validation
- **WHEN** `_dispatch_tool` runs `spec.input_model.model_validate(args)` and catches `ValidationError`
- **THEN** the returned envelope SHALL have `kind == "validation"`
- **AND** the envelope's `internal_message` SHALL begin with `"ValidationError:"`
- **AND** the `user_hint` SHALL be a generic zh-TW phrasing such as "查詢條件有點不太對" (validation-flavoured)

#### Scenario: Unknown exception falls back gracefully

- **GIVEN** a tool callable raises an exception type not in the classifier dispatch table (e.g. `RuntimeError`)
- **WHEN** `_dispatch_tool` catches the exception
- **THEN** the returned envelope SHALL have `kind == "unknown"`
- **AND** the envelope's `user_hint` SHALL be a generic zh-TW phrasing such as "這次查詢遇到一點狀況"

### Requirement: Agent system prompt SHALL instruct the LLM to use `user_hint` and never expose internal error details

The agent system prompt (assembled by `backend/app/services/chat_agent/memory.py::build_messages`) SHALL include an explicit rule and example that direct the LLM, when a tool result contains `"ok": false`, to base its user-facing response on the envelope's `user_hint` field; the LLM SHALL NOT output `internal_message`, exception class names (e.g. `ProgrammingError`, `IntegrityError`), or phrases that imply internal system failure (e.g. "技術問題", "系統查詢時遇到", "資料存取似乎遇到問題").

#### Scenario: Tool result with `ok: false` produces user-friendly answer

- **GIVEN** the agent system prompt is loaded and a tool returns `{"ok": false, "kind": "schema", "internal_message": "ProgrammingError: column ts.start_seconds does not exist", "user_hint": "這次查詢沒撈到完整資料"}`
- **WHEN** the LLM produces the final answer in the next round
- **THEN** the answer text SHALL be a paraphrase / extension of `user_hint`
- **AND** the answer SHALL NOT contain `"ProgrammingError"`, `"column ts.start_seconds"`, `"技術問題"`, `"系統查詢"`, or `"資料存取"`

### Requirement: `_get_episode_segments` SQL SHALL reference the real `transcript_segments` columns

The SQL query in `backend/app/services/chat_agent/tools.py::_EPISODE_SEGMENTS_SQL` SHALL select `ts.start_time` and `ts.end_time` (aliased to `start_sec` and `end_sec` for the LLM response payload) and SHALL `ORDER BY ts.start_time ASC`. The previous column references `ts.start_seconds` / `ts.end_seconds` do not exist on the `transcript_segments` table per the `TranscriptSegment` model and SHALL NOT appear in the SQL.

#### Scenario: `_get_episode_segments` succeeds on prod schema

- **GIVEN** an episode with at least one transcript segment row in `transcript_segments`
- **WHEN** the agent invokes `get_episode_segments(episode_id, topic_filter=None)`
- **THEN** the tool result SHALL be a dict with key `segments` containing a non-empty list
- **AND** each segment SHALL have `start_sec` and `end_sec` as numeric values from the row's `start_time` / `end_time` columns
- **AND** the underlying SQL execution SHALL NOT raise `ProgrammingError`
