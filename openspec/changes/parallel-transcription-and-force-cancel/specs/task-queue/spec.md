## ADDED Requirements

### Requirement: Worker service runs with multiple replicas in production

In production deployments (Zeabur), the `worker` service SHALL run with exactly 3 replicas, each with `--concurrency=1` (one Celery worker process per replica, one task per process at a time). Real concurrent transcription capacity SHALL therefore be 3 (replicas × concurrency).

The dispatcher's logical cap (`app_settings.max_concurrent_transcriptions`, range 1–3) SHALL never exceed the replica count. The system SHALL NOT attempt to auto-scale replicas based on the setting; the replica count is a fixed deployment-level constant.

If a replica process crashes or is terminated, in-flight tasks SHALL rely on the existing stale-running detection (dispatcher's TTL-based throttle slot) and the queue's row-level status tracking for recovery. This change does NOT introduce new graceful-drain or task-handover logic.

#### Scenario: Three replicas process three tasks in parallel

- **GIVEN** worker service has 3 replicas running, each with `--concurrency=1`
- **AND** `app_settings.max_concurrent_transcriptions = 3`
- **WHEN** the dispatcher sends 3 transcribe_episode tasks to the broker
- **THEN** each replica SHALL pick up exactly one task within 5 seconds of dispatch
- **AND** all 3 tasks SHALL be in `running` simultaneously (started_at within a 10-second window)

#### Scenario: Setting cap below replica count leaves replicas idle

- **GIVEN** worker service has 3 replicas running
- **AND** `app_settings.max_concurrent_transcriptions = 1`
- **WHEN** 5 episodes are enqueued
- **THEN** the dispatcher SHALL dispatch tasks one at a time
- **AND** at most 1 replica SHALL be processing at any moment; 2 replicas SHALL remain idle
