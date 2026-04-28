## ADDED Requirements

### Requirement: Worker service runs with concurrency 3 in production

In production deployments (Zeabur), the `worker` service SHALL run a Celery worker with `--concurrency=3` (single replica with 3 prefork worker processes, one task per process at a time). Real concurrent transcription capacity SHALL therefore be 3.

The dispatcher's logical cap (`app_settings.max_concurrent_transcriptions`, range 1–3) SHALL never exceed the worker concurrency. The system SHALL NOT attempt to auto-scale based on the setting; the concurrency value is a fixed deployment-level constant configured via the `START_COMMAND` environment variable on the worker service.

If a worker process crashes or is terminated, in-flight tasks SHALL rely on the existing stale-running detection (dispatcher's TTL-based throttle slot) and the queue's row-level status tracking for recovery. Celery prefork SHALL automatically respawn crashed worker processes within the same container.

#### Scenario: Worker concurrency 3 processes three tasks in parallel

- **GIVEN** worker service is running with `--concurrency=3` (single replica, 3 prefork processes)
- **AND** `app_settings.max_concurrent_transcriptions = 3`
- **WHEN** the dispatcher sends 3 transcribe_episode tasks to the broker
- **THEN** each prefork process SHALL pick up exactly one task within 5 seconds of dispatch
- **AND** all 3 tasks SHALL be in `running` simultaneously (started_at within a 10-second window)

#### Scenario: Setting cap below worker concurrency leaves processes idle

- **GIVEN** worker service is running with `--concurrency=3`
- **AND** `app_settings.max_concurrent_transcriptions = 1`
- **WHEN** 5 episodes are enqueued
- **THEN** the dispatcher SHALL dispatch tasks one at a time
- **AND** at most 1 prefork process SHALL be processing at any moment; the other 2 SHALL remain idle
