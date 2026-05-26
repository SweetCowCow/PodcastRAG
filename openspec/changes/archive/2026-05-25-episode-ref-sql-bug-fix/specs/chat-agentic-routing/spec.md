## ADDED Requirements

### Requirement: Episode reference resolver SQL SHALL NOT collide with SQLAlchemy bind syntax

The `find_by_ref` resolver in `backend/app/services/episode_finders.py` SHALL NOT use PCRE non-capturing groups (`(?:...)`) inside SQL text passed to `sqlalchemy.text()`, because SQLAlchemy parses any `:identifier` token (including `:EP`, `:集` embedded inside `(?:EP|第)` / `(?:集)?`) as a bind parameter placeholder and raises `StatementError: A value is required for bind parameter 'EP'` at execute time. Equivalent boolean-match semantics SHALL be obtained by using plain capturing groups (`(EP|第)`, `(集)?`) instead, since the `title ~*` operator returns only a boolean and never references capture group output.

#### Scenario: find_by_ref resolves EP-number reference without raising

- **GIVEN** an episode with title containing `EP143` exists in the show
- **WHEN** the agent calls `find_episode_by_ref(ref="EP143")`
- **THEN** `find_by_ref` SHALL execute the EP-number SQL without raising `StatementError`
- **AND** SHALL return an `EpisodeRef` whose `episode_id` matches the episode

#### Scenario: find_by_ref resolves Chinese ordinal reference without raising

- **GIVEN** an episode with title containing `EP19` exists in the show
- **WHEN** the agent calls `find_episode_by_ref(ref="第19集")`
- **THEN** `find_by_ref` SHALL execute the EP-number SQL without raising `StatementError`
- **AND** SHALL return the same `EpisodeRef` as `find_episode_by_ref(ref="EP19")` would

#### Scenario: find_by_ref returns None for unmatched EP-number

- **GIVEN** no episode with title containing `EP999` exists in the show
- **WHEN** the agent calls `find_episode_by_ref(ref="EP999")`
- **THEN** `find_by_ref` SHALL execute the EP-number SQL without raising
- **AND** SHALL fall back to the title-ILIKE SQL
- **AND** SHALL return `None` when both queries find no row

#### Scenario: SQL string contains no PCRE non-capturing group syntax

- **GIVEN** the `_BY_REF_EP_NUMBER_SQL` constant in `backend/app/services/episode_finders.py`
- **WHEN** a regression test asserts on the SQL string
- **THEN** the SQL string SHALL NOT contain the substring `(?:`
- **AND** the SQL string SHALL still match an episode title containing `EP143` when executed against a row whose `title` is `EP143｜某集標題`
