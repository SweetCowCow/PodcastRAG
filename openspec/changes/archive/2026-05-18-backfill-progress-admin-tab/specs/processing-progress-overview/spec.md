## ADDED Requirements

### Requirement: Processing stats admin endpoint

The backend SHALL expose `GET /admin/processing-stats` (admin role + CSRF required) returning JSON:

```json
{
  "transcription": {"completed_episodes": 414, "total_episodes": 556, "ratio": 0.745},
  "summary":       {"completed_episodes": 414, "total_episodes": 414, "ratio": 1.0},
  "topic_seg":     {"completed_segments": 277000, "total_segments": 700000, "ratio": 0.396, "completed_episodes": 113, "total_episodes_with_transcript": 414, "episode_ratio": 0.273},
  "last_24h": {
    "transcribed_episodes": 5,
    "labeled_segments": 47000,
    "failures": [{"task_name": "transcribe_episode", "count": 10, "sample_error": "413 Maximum content size limit exceeded"}, ...]
  },
  "as_of": "2026-05-10T11:30:00Z"
}
```

Numbers SHALL be computed via SQL queries on `episodes`, `transcripts`, `transcript_segments`. The `topic_seg` field SHALL include both `completed_segments / total_segments` (more precise) AND `completed_episodes / total_episodes_with_transcript` (per-episode count) so the frontend can show whichever matches the bar's intent. Failures in `last_24h` SHALL come from Celery result backend by scanning `celery-task-meta-*` keys with `status=FAILURE` and `date_done` within 24 hours, grouped by `task_name`. After F2 ships, the implementation SHALL switch to reading from `task_failure_log` table (same response shape).

#### Scenario: Endpoint returns three-dimensional progress

- **WHEN** admin calls `GET /admin/processing-stats`
- **THEN** the response SHALL be 200 JSON containing `transcription`, `summary`, `topic_seg`, `last_24h`, `as_of` keys

#### Scenario: topic_seg uses both segment and episode counts

- **GIVEN** there are 414 transcripts completed, 113 episodes have any topic_label, total transcript_segments = 700K, labeled = 277K
- **WHEN** admin calls the endpoint
- **THEN** the response SHALL contain `topic_seg.completed_segments=277000` AND `topic_seg.completed_episodes=113`
- **AND** SHALL include both `ratio=0.396` (segment ratio) and `episode_ratio=0.273` (episode ratio)

#### Scenario: last_24h failures grouped by task_name

- **GIVEN** Celery result backend has 10 FAILURE entries for transcribe_episode and 4 for classify_episode_topics within 24h
- **WHEN** admin calls the endpoint
- **THEN** `last_24h.failures` SHALL be `[{task_name: "app.workers.tasks.transcribe_episode", count: 10, sample_error: "..."}, {task_name: "app.workers.topic_task.classify_episode_topics", count: 4, sample_error: "..."}]`

#### Scenario: Non-admin gets 403

- **WHEN** a non-admin user calls the endpoint
- **THEN** the response SHALL be 403 Forbidden

---

### Requirement: Admin Queue Tab shows processing overview

The admin frontend SHALL render a new `<ProcessingOverview>` block at the top of the existing Queue Tab page (above the per-row queue table). The block SHALL contain:

1. Three progress rows (轉錄 / 摘要 / 分類), each showing:
   - Label in zh + en (per CLAUDE.md i18n rule)
   - Progress bar (CSS-only, `<div>` with `width: <ratio>%`, no chart library)
   - Numeric ratio: `X / Y 集 (Z%)` for transcription / summary; `X / Y 段 (Z%)` for topic_seg (segment-level primary); also display `(M / N 集已完整標完)` in muted secondary text for topic_seg
2. "最近 24 小時" section:
   - "轉錄 +N 集 / 分類 +N 段（≈M 集邊際進度）/ 失敗 N 件"
   - "[查看失敗清單]" expandable button — click to expand a small table listing task_name × count × sample_error (truncated to 100 chars)
3. "上次更新：HH:MM 台北" small text bottom-right
4. Auto-poll every 30 seconds; on poll error show "更新失敗，重試中..." text without breaking the existing queue table below

The block SHALL appear regardless of whether queue table is empty (e.g. all completed). Time displayed in Asia/Taipei. All text bilingual (zh primary + en i18n key per existing pattern).

#### Scenario: All three progress rows render with bars

- **GIVEN** stats endpoint returns transcription ratio 0.745, summary 1.0, topic_seg ratio 0.396
- **WHEN** admin loads the Queue Tab
- **THEN** three progress rows SHALL render in order 轉錄 / 摘要 / 分類
- **AND** the bar widths SHALL be 74.5%, 100%, 39.6% respectively

#### Scenario: topic_seg shows segment AND episode counts

- **GIVEN** topic_seg.completed_segments=277000, total=700000, completed_episodes=113, total_episodes_with_transcript=414
- **WHEN** admin views the row
- **THEN** the row SHALL show "分類 — 277,000 / 700,000 段 (39.6%)"
- **AND** below it SHALL show in muted text "(113 / 414 集已完整標完)"

#### Scenario: 24h failures expandable

- **GIVEN** last_24h.failures contains 2 entries
- **WHEN** admin clicks "[查看失敗清單]" button
- **THEN** an inline table SHALL expand showing both entries with task_name and count
- **AND** clicking again SHALL collapse it

#### Scenario: 30s auto-poll updates ratios

- **GIVEN** the page is open with transcription ratio 0.74
- **AND** in the next 30 seconds, 5 more episodes complete transcription
- **WHEN** the polling interval fires
- **THEN** the displayed ratio SHALL update to reflect the new value

#### Scenario: Poll error shows transient warning

- **GIVEN** the /admin/processing-stats endpoint returns 500 once
- **WHEN** the poll fires
- **THEN** a small "更新失敗，重試中..." text SHALL appear inside the overview block
- **AND** the rest of the Queue Tab page (queue table) SHALL remain functional
- **AND** the next successful poll SHALL clear the warning
