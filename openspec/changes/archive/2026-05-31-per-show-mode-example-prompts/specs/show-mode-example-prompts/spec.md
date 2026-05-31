## ADDED Requirements

### Requirement: Per-show per-mode example prompt generation

The backend SHALL generate guiding example questions for each show, separately for each of the three query modes (`index`, `semantic`, `chat`), using that show's existing materials (`episodes.ai_summary`, `episodes.guests`, and topic terms) as input to an LLM. Generation SHALL produce 2–3 example questions per mode, written in the style appropriate to that mode (index: concrete keyword/entity questions; semantic: descriptive questions; chat: cross-episode synthesis questions). Generated prompts SHALL be persisted to a `show_example_prompts` store keyed by `show_id`, `mode`, and `ordinal`. Generation SHALL be idempotent for a given show (re-running replaces that show's prior prompts). Generation SHALL be fail-open: an LLM error or insufficient materials SHALL skip persistence without raising into any ingest chain.

#### Scenario: Generation writes per-mode prompts for a show with materials

- **GIVEN** a show whose episodes have `ai_summary` and `guests` populated
- **WHEN** generation runs for that show
- **THEN** the `show_example_prompts` store SHALL contain at least one prompt for each of `index`, `semantic`, and `chat`

#### Scenario: Insufficient materials skips without error

- **GIVEN** a show whose episodes have no `ai_summary` and no `guests`
- **WHEN** generation runs for that show
- **THEN** no prompts SHALL be written AND no error SHALL propagate to the caller

#### Scenario: Re-running generation replaces prior prompts

- **GIVEN** a show that already has generated example prompts
- **WHEN** generation runs again for that show
- **THEN** the prior prompts for that show SHALL be replaced (not duplicated)

### Requirement: Example prompts retrieval endpoint

The backend SHALL expose `GET /shows/{show_id}/example-prompts` returning the stored prompts grouped by mode as `{ "index": string[], "semantic": string[], "chat": string[] }`, each array ordered by `ordinal`. For a show with no generated prompts, the endpoint SHALL return the three keys each mapping to an empty array. The endpoint SHALL be public (no authentication) and SHALL NOT trigger any LLM generation on read.

#### Scenario: Endpoint returns per-mode arrays

- **GIVEN** a show with generated prompts for all three modes
- **WHEN** the client GETs `/shows/{show_id}/example-prompts`
- **THEN** the response SHALL contain `index`, `semantic`, and `chat` arrays each ordered by `ordinal`

#### Scenario: Ungenerated show returns empty arrays

- **GIVEN** a show with no generated prompts
- **WHEN** the client GETs `/shows/{show_id}/example-prompts`
- **THEN** the response SHALL be `{ "index": [], "semantic": [], "chat": [] }` AND no LLM call SHALL occur

### Requirement: Generation triggered on ingest and via admin backfill

Example prompt generation SHALL be enqueued for a show after that show's episode summaries complete (chained from the existing summary pipeline), and SHALL also be runnable on demand through an admin-authenticated backfill action that targets a single show or all shows.

#### Scenario: Admin backfill regenerates for an existing show

- **GIVEN** an existing show with episodes already summarized
- **WHEN** an admin triggers the backfill for that show
- **THEN** generation SHALL run for that show and the stored prompts SHALL reflect the latest run

### Requirement: Per-mode input placeholder

Each of the three query mode input fields SHALL display a mode-specific placeholder string (static, localized via i18n): the Index input guides toward keyword/entity input, the Semantic input guides toward a descriptive query, and the Chat input guides toward a cross-episode question.

#### Scenario: Each mode shows its own placeholder

- **WHEN** the user views the Index, Semantic, and Chat tabs
- **THEN** each tab's input SHALL show a distinct placeholder phrased for that mode

### Requirement: Example chips fall back from trending to generated prompts

The chip row above each mode's input SHALL prefer trending queries: when `GET /shows/{id}/trending-queries` returns at least 3 entries, those trending chips SHALL render. When fewer than 3 trending entries exist for the show, the chip row SHALL instead render that mode's generated example prompts (fetched from `GET /shows/{id}/example-prompts`), visually labelled as examples rather than trending. When neither source yields entries, no chip row SHALL render. Clicking any chip SHALL populate the input with that text and execute the query for the current mode.

#### Scenario: Cold-start show shows generated example chips

- **GIVEN** a show with fewer than 3 trending entries and generated example prompts for the current mode
- **WHEN** the query page renders that mode
- **THEN** the chip row SHALL display the mode's generated example prompts labelled as examples

#### Scenario: Popular show shows trending chips

- **GIVEN** a show with at least 3 trending entries
- **WHEN** the query page renders
- **THEN** the chip row SHALL display trending chips, not generated examples

#### Scenario: Clicking an example chip runs the query

- **GIVEN** a rendered example chip with text "歌單"
- **WHEN** the user clicks it
- **THEN** the current mode's input SHALL be populated with "歌單" AND the query SHALL execute
