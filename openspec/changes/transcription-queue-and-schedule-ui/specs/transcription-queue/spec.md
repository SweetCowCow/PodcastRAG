## ADDED Requirements

### Requirement: Reorder pending row position

The backend SHALL expose `PATCH /admin/queue/{queue_id}/position` accepting body `{"position": <int>}`. The endpoint SHALL only accept rows with `status=pending`; for any other status the endpoint SHALL return HTTP 409 Conflict.

The endpoint SHALL clamp the requested position to the valid range `[min(pending.position), max(pending.position)]` (inclusive). After clamping, the endpoint SHALL recompute pending row positions in a single transaction:

- If the clamped new position is less than the row's current position (move-forward), all pending rows whose position is in `[new_pos, old_pos)` SHALL have their position incremented by 1, and the target row's position SHALL be set to new_pos.
- If the clamped new position is greater than the row's current position (move-backward), all pending rows whose position is in `(old_pos, new_pos]` SHALL have their position decremented by 1, and the target row's position SHALL be set to new_pos.
- If the clamped new position equals the row's current position, the endpoint SHALL be a no-op and SHALL still return HTTP 200.

Only rows with `status=pending` SHALL be touched by the recompute; rows with other statuses SHALL retain their position values.

The endpoint SHALL return the updated target row as `QueueRowOut` on HTTP 200.

#### Scenario: Move pending row forward

- **GIVEN** pending rows ordered by position: `A(pos=10), B(pos=11), C(pos=12)`
- **WHEN** a client calls `PATCH /admin/queue/C.id/position` with body `{"position": 10}`
- **THEN** in one transaction A SHALL become position=11, B SHALL become position=12, C SHALL become position=10
- **AND** the response SHALL be HTTP 200 with C's updated row body

#### Scenario: Move pending row backward

- **GIVEN** pending rows ordered by position: `A(pos=10), B(pos=11), C(pos=12)`
- **WHEN** a client calls `PATCH /admin/queue/A.id/position` with body `{"position": 12}`
- **THEN** B SHALL become position=10, C SHALL become position=11, A SHALL become position=12
- **AND** the response SHALL be HTTP 200

#### Scenario: Position out of range is clamped

- **GIVEN** pending rows have positions `[10, 11, 12]`
- **WHEN** a client calls `PATCH /admin/queue/{id}/position` with body `{"position": 999}`
- **THEN** the position SHALL be clamped to 12 (max of pending)
- **AND** the move-backward recompute SHALL apply
- **AND** the response SHALL be HTTP 200

#### Scenario: Reordering a non-pending row is rejected

- **WHEN** a client calls `PATCH /admin/queue/{id}/position` for a row with `status=running`
- **THEN** the backend SHALL return HTTP 409 Conflict
- **AND** no positions SHALL be modified

#### Scenario: No-op when target equals current

- **GIVEN** a pending row at position 11
- **WHEN** a client calls PATCH with `{"position": 11}`
- **THEN** no row positions SHALL change
- **AND** the response SHALL be HTTP 200
