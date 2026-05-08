## ADDED Requirements

### Requirement: Per-segment topic label populated by LLM classifier

The backend SHALL provide a topic-segmentation pipeline that classifies every `transcript_segments` row into one label drawn from a per-show union of universal categories and show-specific extension categories. Each segment SHALL be classified independently with single-label output. The pipeline SHALL persist the result to `transcript_segments.topic_label`.

The universal label set SHALL be exactly: `intro`, `outro`, `sponsor`, `topic_main`, `anecdote`, `guest_intro`, `factual`, `meta`.

Show-specific extensions SHALL be loaded from `shows.segment_categories` (a JSONB column holding an array of `{name: str, desc: str}` objects). The LLM prompt SHALL list both universal labels and the show's extension labels, and the model SHALL be instructed to choose exactly one.

#### Scenario: Universal labels populated

- **GIVEN** a show with `shows.segment_categories = '[]'`
- **WHEN** `backfill_topic_labels.py --episode-id <ep>` runs against an episode of that show
- **THEN** every `transcript_segments` row in that episode SHALL have `topic_label` set to one of the 8 universal label strings

#### Scenario: Per-show extension label permitted

- **GIVEN** a show with `shows.segment_categories = '[{"name":"playlist_segment","desc":"..."}]'`
- **WHEN** the backfill runs against an episode of that show
- **THEN** segments matching the playlist behaviour SHALL be permitted to carry `topic_label='playlist_segment'` (instead of the universal `topic_main`)

#### Scenario: Single-label output enforced

- **WHEN** the LLM returns multiple labels for one segment (model error)
- **THEN** the pipeline SHALL persist only the first label and SHALL log a warning containing `episode_id` and `segment_id`

#### Scenario: Short segment fallback

- **GIVEN** a segment whose `end_time - start_time < 5.0` seconds
- **WHEN** the LLM is asked to classify it
- **THEN** the pipeline MAY substitute the previous segment's label rather than calling the LLM separately for that single segment, to reduce noise on Whisper filler segments

##### Example: Universal label set

| Label | Trigger phrase example |
| --- | --- |
| `intro` | 「歡迎大家收聽台通，我是阿揆」 |
| `outro` | 「下集再會」「謝謝收聽」 |
| `sponsor` | 「優惠碼 TC10」「最近我們跟 XX 品牌合作」 |
| `topic_main` | 主題核心討論段 |
| `anecdote` | 「我之前去吃裴社長介紹的那家」 |
| `guest_intro` | 「今天請到馬世芳，他是」 |
| `factual` | 「這家餐廳在中山區安東街」 |
| `meta` | 「這是我們第 100 集」「我們之前講過」 |

### Requirement: Bulk backfill script

The repository SHALL contain `backend/scripts/backfill_topic_labels.py` accepting `--all` (every transcript with `status='completed'`) or `--episode-id <UUID>`. For each episode, the script SHALL load all segments, send a single LLM call (gpt-4o-mini via the configured `summary` step base_url + api_key) with structured JSON output, and UPDATE every segment's `topic_label`. The script SHALL print per-episode progress (`episode_id`, segment count, label distribution) and a final summary (`episodes=N, segments=M, errors=E`).

The script SHALL be resilient: a single-episode failure SHALL log + continue, not abort the run.

#### Scenario: --all processes every completed transcript

- **WHEN** the backfill runs `--all` against a corpus of 354 completed transcripts
- **THEN** every segment whose transcript has `status='completed'` SHALL eventually have a non-null `topic_label` (within retry budget)
- **AND** the final summary SHALL print `episodes=N segments=M errors=E` with `errors` recording episodes that failed all retries

#### Scenario: Per-episode failure does not abort

- **GIVEN** episode E1's LLM call raises an OpenAI 5xx error after retries exhausted
- **WHEN** processing continues to episode E2
- **THEN** E2 SHALL be processed normally and the summary SHALL include `errors >= 1`

### Requirement: Admin audit endpoint surfaces a random sample

The backend SHALL expose `GET /admin/topic-seg/audit-sample?n=<int>` (admin-gated) that returns a JSON array of randomly sampled segments with their `topic_label` and surrounding context. Each item SHALL include:

- `segment_id`, `episode_id`, `episode_title`
- `start_time`, `end_time`
- `text` (the segment itself)
- `topic_label`
- `prev_text` (previous segment's text, or null at episode boundary)
- `next_text` (next segment's text, or null at episode boundary)
- `is_show_specific_label` (boolean — true if `topic_label` is in the show's `segment_categories` extension list)

The default `n` SHALL be 50 and the maximum SHALL be 200. Sampling SHALL be uniform random across all segments with non-null `topic_label`.

#### Scenario: Default sample size

- **WHEN** an admin calls `GET /admin/topic-seg/audit-sample`
- **THEN** the response SHALL be HTTP 200 with up to 50 segments

#### Scenario: Show-specific label flagged

- **GIVEN** a segment carrying `topic_label='playlist_segment'` from a show whose `segment_categories` includes `playlist_segment`
- **WHEN** that segment appears in the audit sample
- **THEN** its `is_show_specific_label` SHALL be `true`

#### Scenario: Non-admin denied

- **WHEN** an authenticated non-admin user calls the endpoint
- **THEN** the response SHALL be HTTP 403 with `error_code='forbidden'`

### Requirement: Admin audit UI surfaces context for human review

The frontend SHALL contain `src/AdminTopicSegAuditTab.jsx` registered at admin route `admin-topic-seg-audit` and listed in `Shared.jsx` admin sidebar. The page SHALL fetch `/admin/topic-seg/audit-sample` and render each row with the previous segment, the target segment (with its `topic_label` highlighted), and the next segment laid out in three lines.

The page SHALL provide a "重抽樣" (re-sample) button that re-fetches a fresh sample.

#### Scenario: Page renders three-line context per item

- **WHEN** the audit page loads
- **THEN** each list item SHALL show three rows: `prev_text`, `text` (with the label rendered as a coloured badge), `next_text`
- **AND** if `prev_text` or `next_text` is null, that row SHALL render as muted "（節目開頭）" / "（節目結尾）"

#### Scenario: Show-specific labels styled distinctly

- **WHEN** a row's `is_show_specific_label` is `true`
- **THEN** the label badge SHALL render with a distinct (non-default) colour so the reviewer can spot show-specific calls quickly
