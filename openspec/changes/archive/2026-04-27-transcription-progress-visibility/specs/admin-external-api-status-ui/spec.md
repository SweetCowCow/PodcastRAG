## ADDED Requirements

### Requirement: Admin page exposes an External API Status tab

The admin UI SHALL render a dedicated tab named "External API Status" (Chinese label: "外部 API 狀態") that displays one card per tracked external API consuming `GET /admin/external-api-status`, polled at a fixed 15-second interval while the tab is active, so that administrators can see live health status for OpenAI Whisper, Chat, and Embedding APIs at a glance.

Each API card SHALL render at least: the API's human-readable name, the timestamp of the most recent call (localised relative-time such as "2 分鐘前"), a status badge derived from the most recent event's `ok` flag and `error_category`, and the most recent event's HTTP status code when present. When `latest` is null the card SHALL display a placeholder state ("尚無紀錄" / "No calls recorded yet") and no badge.

Status badge mapping:

| Condition                                    | Badge variant | Label zh      | Label en           |
| -------------------------------------------- | ------------- | ------------- | ------------------ |
| `latest.ok == true`                          | `success`     | 正常          | Healthy            |
| `latest.ok == false && error_category == "quota_exceeded"` | `danger`   | 額度不足      | Quota Exceeded     |
| `latest.ok == false && error_category == "auth_error"`     | `danger`   | 認證錯誤      | Auth Error         |
| `latest.ok == false && error_category == "rate_limited"`   | `warning`  | 速率受限      | Rate Limited       |
| `latest.ok == false && error_category == "server_error"`   | `warning`  | 伺服器錯誤    | Server Error       |
| `latest.ok == false && error_category == "network_error"`  | `warning`  | 網路錯誤      | Network Error      |
| `latest.ok == false && error_category == "unknown"` or null| `muted`    | 未知錯誤      | Unknown Error      |

When the payload reports `degraded = true` for an API, the card SHALL additionally display a subdued notice ("監測服務異常，最近狀態可能不準確" / "Monitoring service degraded; status may be stale").

The tab SHALL stop polling (clear the interval) on unmount and on user-initiated tab switch away from the External API Status tab.

#### Scenario: Healthy API rendered

- **WHEN** the endpoint returns `apis[0] = {name: "openai_whisper", latest: {ts_ms: <2 min ago>, ok: true, ...}, recent: [...], degraded: false}`
- **THEN** the card SHALL show "OpenAI Whisper", a `success` badge labelled "正常" in zh (or "Healthy" in en), and the relative-time "2 分鐘前"
- **AND** SHALL NOT display the degraded notice

#### Scenario: Quota exceeded rendered

- **WHEN** the endpoint returns `apis[0].latest = {ok: false, error_category: "quota_exceeded", http_status: 429, ...}`
- **THEN** the card SHALL show a `danger` badge labelled "額度不足" (zh) / "Quota Exceeded" (en)
- **AND** SHALL display the HTTP status `429`

#### Scenario: No calls yet rendered

- **WHEN** the endpoint returns `apis[i] = {name: "openai_embedding", latest: null, recent: [], degraded: false}`
- **THEN** the card SHALL render the placeholder "尚無紀錄" (zh) / "No calls recorded yet" (en) and SHALL NOT show any badge, timestamp, or HTTP status

#### Scenario: Degraded flag surfaced

- **WHEN** `apis[0].degraded = true`
- **THEN** the card SHALL display the degraded notice below any status badge with a muted visual treatment

#### Scenario: Polling stops on unmount

- **WHEN** the user navigates away from the External API Status tab
- **THEN** the 15-second polling interval SHALL be cleared within the same React event loop turn as unmount
- **AND** no further `GET /admin/external-api-status` requests SHALL be issued until the tab is opened again
