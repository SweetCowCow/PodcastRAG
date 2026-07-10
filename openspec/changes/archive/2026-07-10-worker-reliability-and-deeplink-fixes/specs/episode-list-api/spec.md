## ADDED Requirements

### Requirement: Single-episode endpoint

The backend SHALL expose `GET /episodes/{episode_id}` returning the same shape as one element of the episodes list response (`EpisodeResponse` including `transcript_status` derived by LEFT JOIN on `transcripts`). When no episode exists for the given id, the endpoint SHALL return 404. The endpoint SHALL sit at the same auth level as the episodes list endpoint (public read).

#### Scenario: Existing episode returns 200 with transcript status

- **WHEN** a client calls `GET /episodes/{id}` for an episode whose transcript row has `status='completed'`
- **THEN** the response SHALL be 200 with that episode's fields and `transcript_status="completed"`

#### Scenario: Unknown episode returns 404

- **WHEN** a client calls `GET /episodes/{id}` with a UUID that matches no episode
- **THEN** the response SHALL be 404

### Requirement: URL deep-link resolves episodes via the single-episode endpoint

The frontend URL deep-link receiver (query parameters `show_id`, `episode_id`, optional `t`) SHALL resolve the target episode by calling `GET /episodes/{episode_id}` instead of searching the paginated episodes list. A deep-link to any episode of a show — regardless of the episode's position in the catalog — SHALL land on that episode's transcript page with the `t` timestamp applied. The existing silent fallback to the landing page SHALL apply only when the show or episode genuinely does not exist or the fetch fails.

#### Scenario: Deep-link to an episode outside the newest 50 lands on the transcript page

- **GIVEN** a show with more than 50 episodes and a target episode older than the newest 50
- **WHEN** the app loads with `?show_id=<show>&episode_id=<that episode>&t=600`
- **THEN** the transcript page for that episode SHALL render, scrolled to the segment nearest 600 seconds

#### Scenario: Deep-link to a nonexistent episode falls back silently

- **WHEN** the app loads with an `episode_id` that returns 404
- **THEN** the app SHALL clear the deep-link parameters and show the landing page without an error popup

### Requirement: Episode panel transcribed count reflects the backend total

The QueryPage episode panel's "transcribed episodes" counter SHALL use the show-level `transcribed_count` provided by the backend as its numerator, not a count derived from the currently loaded (paginated) episode list. The denominator SHALL remain the show's `episode_count`.

#### Scenario: Counter shows the backend total when the panel is partially loaded

- **GIVEN** a show with 565 episodes of which 563 are transcribed, and an episode panel that has loaded only the newest 200
- **WHEN** the QueryPage renders the counter
- **THEN** it SHALL display 563 / 565
