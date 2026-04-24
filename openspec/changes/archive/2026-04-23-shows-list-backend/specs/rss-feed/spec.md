## MODIFIED Requirements

### Requirement: List shows endpoint

The backend SHALL expose `GET /shows` returning all registered shows ordered by `created_at` descending. Each show record in the response SHALL include `id`, `title`, `description`, `rss_url`, `image_url`, `language`, `created_at`, `episode_count`, and `transcribed_count`. The `transcribed_count` SHALL equal the number of episodes belonging to the show whose `transcripts.status` is `'completed'`.

#### Scenario: Shows listed with episode and transcript counts

- **WHEN** `GET /shows` is called and a show has 10 episodes of which 3 have a linked `transcripts` row with `status = 'completed'`
- **THEN** the response record for that show SHALL contain `episode_count = 10` and `transcribed_count = 3`

#### Scenario: Show with no transcribed episodes

- **WHEN** `GET /shows` is called and a show has 5 episodes but none has a `completed` transcript
- **THEN** the response record for that show SHALL contain `transcribed_count = 0`

#### Scenario: Shows listed ordered newest-first

- **WHEN** `GET /shows` is called and 3 shows exist
- **THEN** the response SHALL be HTTP 200 with a JSON array of 3 show records ordered by `created_at` descending, each containing the full set of fields above

#### Scenario: No shows yet

- **WHEN** `GET /shows` is called with an empty `shows` table
- **THEN** the response SHALL be HTTP 200 with an empty JSON array
