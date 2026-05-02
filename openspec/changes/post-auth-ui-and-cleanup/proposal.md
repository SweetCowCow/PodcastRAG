## Summary

兩個 UI 視覺重整（更新日誌時間軸 + 轉錄佇列子分頁排序與編號）+ 三項 authentication-system 留下的技術債清理（empty-state 導向、STATS live fetch、admin pytest auth fixture）。

## Motivation

**UI 部分**：
- 更新日誌目前是分組卡片網格，視覺上看不出「時間流」；改成單條垂直時間軸（最新在上）能讓使用者一眼看到發布節奏
- 轉錄佇列「進行中」子分頁包含 pending + running 兩種狀態，目前混在一起；使用者在 admin 操作時希望「執行中的集數先看到」，並能一眼判斷 pending 集數的排隊位置

**Cleanup 部分**：authentication-system change 期間刻意延後的三項技術債：
1. `PodcastSelect.jsx` 空狀態還在呼叫 `POST /shows`，但這個 endpoint 現已加 admin gate（一般使用者打了會 403），UX 不佳，應改成導去後台讓 admin 加節目
2. Release log 頁面的 STATS_VECTORS_COUNT 是寫死估算值（137 集 × ~50 chunks）；需要 admin 後台查 prod DB 才能更新，現在透過 zeabur-service-exec 又會撞 Cloudflare 524。應加一個 `GET /admin/stats` endpoint 讓前端 live fetch 真值
3. authentication-system archive 後 23 個既有 admin endpoint pytest 全部失敗（沒帶 auth cookie 直接 401）— 需 conftest 加 auth fixture 修復

## Proposed Solution

### UI: 更新日誌改時間軸
- `ReleaseLogPage.jsx` 排版重構：改成單條垂直時間軸，每筆 entry 對應一個節點（圓點），左側為日期 + 月/日 標籤，右側為 title + summary 卡片
- 保留 milestone 區塊標題（v0.5 / v0.4 ...）作為時間軸的「分段大標」
- 保留現有資料來源（`releaseLog.jsx` 的 RELEASE_LOG）— 不動架構
- 手機版：時間軸改貼齊左邊，避免 cards 被擠壓

### UI: 轉錄佇列「進行中」子分頁排序
- `QueueTab.jsx` 「進行中」子分頁 (`active`) 內：所有 `running` 排在所有 `pending` 上方（保留各狀態內原本的排序邏輯）
- 每筆 `pending` row 在最前面顯示一個排隊序號 badge，從 1 開始遞增（依該 row 在 pending 段內的位置）
- `running` rows 不顯示序號（顯示其他 status badge 即可）

### Cleanup: Empty-state 導向
- `PodcastSelect.jsx` 當 `shows.length === 0` 時，原本的「新增節目」CTA 改為：
  - 已登入且 role=admin → 導向後台「節目管理」（`admin-rag` 或對應頁，視 routing）
  - 其他情況 → 顯示「請聯絡管理員加入節目」雙語提示（不顯示 CTA）

### Cleanup: STATS live fetch
- 後端新增 `GET /admin/stats` endpoint（受 `require_admin` 保護），回傳 `{episodes_completed: int, transcript_chunks: int, shows: int, users: int}`
- `releaseLog.jsx` 的 STATS_*_COUNT 改為動態：先用 hardcoded 值當 fallback；mount 時打 `/admin/stats`，成功就覆寫；admin 才能看到真實 live 數字（因 endpoint 受 gate），其他使用者看 fallback
- 因 Release log 是公開頁（未登入也可看），fallback 保留現有寫死值

### Cleanup: pytest auth fixture
- `tests/conftest.py` 新增 `auth_admin_client` 與 `auth_member_client` fixtures：建一筆 admin/member user + session row，產生 session cookie，回 `AsyncClient`
- 既有 23 個 admin endpoint test 改用該 fixture（移除原本未帶 cookie 的 raw fetch）
- 保留 1-2 個原本的 401 / 403 negative test（驗 unauthenticated 仍被擋）

## Non-Goals

- **不改 release log 資料結構**（仍用 `RELEASE_LOG` array），只動視覺
- **不重寫 Queue 各 column 的內容**（cancel/force-cancel/retry 按鈕、tooltip 等保持原樣）
- **不做 stats endpoint 的細部統計**（如每月趨勢、per-user breakdown）— 那是未來 U3 dashboard change
- **不重構 ApiKeysTab**（那是另一個 change `admin-llm-keys-integration`）
- **不做時間軸動畫 / 過場效果**（YAGNI）

## Alternatives Considered

- **Release log 改 horizontal timeline**：會在手機版斷掉 + 內容被壓縮；vertical 比較可擴展
- **Stats endpoint 不做 gate，所有人能看真值**：揭露 internal metrics 給陌生使用者沒必要；維持 admin gate + fallback 對非 admin 顯示寫死值
- **pytest 用 dependency override 全 mock auth**：改太多既有 test，且失去整合測試價值；走真實 fixture（建 user + session row）較好

## Impact

- Affected specs:
  - Modified: `openspec/specs/release-log-ui/spec.md`、`openspec/specs/admin-transcription-queue-ui/spec.md`、`openspec/specs/admin-show-management-ui/spec.md`、`openspec/specs/backend-core/spec.md`
- Affected code:
  - New:
    - backend/app/api/stats.py
    - backend/app/schemas/stats.py
    - backend/tests/fixtures_auth.py（或加進 conftest.py）
  - Modified:
    - src/ReleaseLogPage.jsx（時間軸版型）
    - src/releaseLog.jsx（live STATS fetch + fallback）
    - src/QueueTab.jsx（active sub-tab 排序 + 編號 badge）
    - src/PodcastSelect.jsx（empty-state CTA 導向）
    - src/i18n.jsx（empty-state 雙語訊息）
    - backend/app/main.py（include stats router）
    - backend/tests/conftest.py（auth fixtures）
    - backend/tests/test_status_endpoints.py、test_queue_cancel.py、test_queue_reorder.py、test_error_responses.py、test_transcribe_task_celery_id.py（採用 fixture）
  - Removed: 無
