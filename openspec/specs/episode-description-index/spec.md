# episode-description-index Specification

## Purpose

TBD - created by archiving change 'r3-1-hybrid-retrieval'. Update Purpose after archive.

## Requirements

### Requirement: Episode description index builder cleans HTML and boilerplate

The backend SHALL provide a `build_description_index_for_episode(episode_id)` function in `backend/app/services/description_indexer.py` that loads `episodes.description`, applies HTML stripping, applies a regex-based boilerplate pattern list, jieba-tokenises the result, requests a single OpenAI embedding for the cleaned text, and UPSERTs one row into `episode_description_chunks` keyed by `episode_id`. The boilerplate pattern list SHALL be a Python module-level constant `BOILERPLATE_PATTERNS: list[str]` of regex strings; the initial seed list SHALL include at minimum `r'^.*鼓勵.*贊助.*$'`, `r'^.*按讚訂閱.*$'`, `r'^.*歡迎收聽下集.*$'`, applied per-line (each line removed if it matches any pattern).

#### Scenario: HTML stripped from description

- **GIVEN** an episode whose `description` is `"<p>本集介紹<a href='x'>顏社</a>的歌單</p>"`
- **WHEN** the indexer runs for that episode
- **THEN** the resulting `text` field SHALL contain `"本集介紹 顏社 的歌單"` (HTML tags removed; links flattened to plain text)

#### Scenario: Boilerplate lines removed

- **GIVEN** an episode whose `description` includes one line `"歡迎收聽下集！"` and another line `"來賓: 馬世芳"`
- **WHEN** the indexer runs
- **THEN** the resulting `text` SHALL include `"來賓: 馬世芳"` and SHALL NOT include `"歡迎收聽下集"`

#### Scenario: Empty description after cleaning is skipped

- **WHEN** an episode's description is empty, all whitespace, or fully matched by boilerplate patterns
- **THEN** the indexer SHALL NOT insert a row into `episode_description_chunks` for that episode
- **AND** any existing row for that episode SHALL be deleted

#### Scenario: Re-index updates existing row

- **GIVEN** a row exists in `episode_description_chunks` for `episode_id=E1`
- **WHEN** `build_description_index_for_episode(E1)` runs again
- **THEN** the existing row SHALL be UPDATED in place (not deleted-and-reinserted)
- **AND** the row's `updated_at` SHALL be set to the current UTC time

#### Scenario: Strip-ratio warning logged for outliers

- **WHEN** boilerplate stripping removes more than 50% of a description's character count
- **THEN** the indexer SHALL log a warning containing the episode_id, original character count, and post-strip character count


<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->

---
### Requirement: Bulk indexer command processes all episodes

The repository SHALL contain `backend/scripts/build_description_index.py`, a CLI tool that accepts `--all` (process every episode with non-empty description) or `--episode-id <UUID>` (process one episode). The script SHALL invoke `build_description_index_for_episode` per episode, batch embedding API calls in groups of at most 64 episodes, and report progress to stdout (one line per batch with the count of inserts / updates / skips).

#### Scenario: --all processes every episode and reports counts

- **WHEN** the script runs with `--all` against a corpus of 354 episodes (340 with non-empty description)
- **THEN** it SHALL log progress lines for each batch
- **AND** the final summary SHALL report total inserts/updates/skips/errors with their sum equal to the count of attempted episodes (340)

#### Scenario: --episode-id processes one episode

- **WHEN** the script runs with `--episode-id <UUID>`
- **THEN** it SHALL invoke `build_description_index_for_episode(<UUID>)` once and exit with code 0 on success or non-zero on failure

#### Scenario: Embedding rate-limit retry

- **WHEN** the OpenAI embeddings API raises `RateLimitError` during a batch
- **THEN** the script SHALL retry the batch up to 3 times with exponential backoff (2s / 4s / 8s)
- **AND** if all retries fail, the script SHALL log the affected episode IDs and continue with the next batch (it SHALL NOT abort the entire run)


<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->

---
### Requirement: Description chunks participate in hybrid retrieval

The retrieval SQL invoked by `/shows/{show_id}/search` and `/shows/{show_id}/query` SHALL execute the same RRF (k=60) ranking against `episode_description_chunks` filtered to the requested `show_id` (joined via `episodes.show_id`), in addition to the equivalent ranking against `transcript_chunks`. The two ranked lists SHALL be combined into a single result set ordered by descending RRF score; each result SHALL retain a `source` field of `"transcript"` or `"description"`.

#### Scenario: Description-only result reaches top-K

- **GIVEN** a query `"顏社的歌單"` whose answer is in the EP description and the corresponding transcript has 0 lexical matches
- **WHEN** the search endpoint runs
- **THEN** the description chunk for that episode SHALL appear in the top-K with `source: "description"`

#### Scenario: Same episode contributing both source types

- **GIVEN** the query matches both the description and one transcript chunk of the same episode
- **WHEN** the search endpoint runs
- **THEN** both results MAY appear in the top-K (the de-duplication is by chunk id, not by episode_id) and SHALL have differing `source` values

##### Example: Source field

| chunk_id | source       | episode_id | start_time |
| -------- | ------------ | ---------- | ---------- |
| `c1`     | `transcript` | `E1`       | 153.42     |
| `d1`     | `description`| `E1`       | (omitted)  |
| `c2`     | `transcript` | `E2`       | 0.00       |

<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->