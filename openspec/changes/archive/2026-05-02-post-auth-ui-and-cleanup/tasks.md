## 1. 後端 — Admin Stats endpoint

- [x] 1.1 建立 `backend/app/schemas/stats.py`：`StatsResponse` 含 `episodes_completed`、`transcript_chunks`、`shows`、`users` 四個 int 欄位（對應「Admin stats endpoint returns aggregate counts」需求）
- [x] 1.2 建立 `backend/app/api/stats.py`：`GET /admin/stats` 用 `select(func.count())` 對四個 table 各做一次 count 查詢，組成回應；router 加 `dependencies=[Depends(require_admin)]`
- [x] 1.3 在 `backend/app/main.py` include 新 stats router
- [x] 1.4 撰寫 pytest `tests/test_admin_stats.py`：覆蓋 admin 200 / member 403 / unauthenticated 401 三情境（依賴 1.7 完成的 fixture）

## 2. 後端 — pytest auth fixture

- [x] 2.1 在 `backend/tests/conftest.py` 新增 `_seed_user(db, role, status)` helper：建一筆 unique email 的 User row 並 commit
- [x] 2.2 新增 `_seed_session(db, user_id)` helper：建一筆 sessions row（plaintext token、`expires_at = now + 1 day`），回傳 raw session token
- [x] 2.3 新增 pytest `auth_admin_cookies` fixture：建 admin user + session，回 dict `{"session_id": token}` 含正確 X-CSRF-Token 推導值（用 `derive_csrf_token`）
- [x] 2.4 新增 `auth_member_cookies` fixture：同上但 role=member
- [x] 2.5 新增便利函式 `csrf_headers(session_token)` 回 `{"X-CSRF-Token": derive_csrf_token(token), "Origin": "http://localhost:8080"}`
- [x] 2.6 fixture 結束時刪除建立的 user 與 session row（cleanup）
- [x] 2.7 暴露 fixtures 至 conftest，讓所有 test file 可直接用

## 3. 後端 — 既有測試套用 fixture

- [x] 3.1 改寫 `tests/test_status_endpoints.py` 中對 `/admin/external-api-status` 的測試，傳入 `auth_admin_cookies` 與 `csrf_headers`（GET 不需 CSRF，但帶 cookie 需要）
- [x] 3.2 改寫 `tests/test_queue_cancel.py` 5 個 test 加入 admin cookie + csrf header（state-changing）
- [x] 3.3 改寫 `tests/test_queue_reorder.py` 5 個 test 加入 admin cookie + csrf header
- [x] 3.4 改寫 `tests/test_error_responses.py` 中受影響的 admin endpoint 測試
- [x] 3.5 改寫 `tests/test_transcribe_task_celery_id.py` 受影響的測試
- [x] 3.6 跑全套 pytest 確認所有 admin endpoint test 通過、新 stats 測試通過、既有 auth 與 CSRF 套件 (test_auth_csrf.py / test_auth_db.py) 仍綠

## 4. 前端 — 更新日誌時間軸

- [x] 4.1 重寫 `src/ReleaseLogPage.jsx`：改成單條 vertical line + 每筆 entry 一個 node + 右側 card 版型；node 顏色用 milestone 對應的 accent（對應「Release log entries render as a single vertical timeline」需求）
- [x] 4.2 加入 milestone marker：當前後 entry milestone 不同時插入分段 label（對應「Milestone section markers appear inline on the timeline」需求）
- [x] 4.3 768px 以下改左對齊版（對應「Mobile timeline collapses to left-aligned variant」需求）
- [x] 4.4 保留 RELEASE_LOG / TAG_LABELS / MILESTONE_LABELS 資料來源不變（不改架構）
- [x] 4.5 在 `index.html` bump ReleaseLogPage.jsx 的 cache buster `?v=`

## 5. 前端 — STATS live fetch

- [x] 5.1 在 `src/releaseLog.jsx` 維持目前寫死的 STATS_*_COUNT 作為 fallback 值
- [x] 5.2 在 `src/ReleaseLogPage.jsx` mount 時打 `apiFetch('/admin/stats')`：成功 200 → 用回應值覆寫顯示；401 / 403 → 沿用 fallback；網路失敗 → 沿用 fallback
- [x] 5.3 顯示 stats 區塊時保留 "as of YYYY-MM-DD" 標籤；live 數字成功取得時把標籤改成 "live"，否則維持原本日期

## 6. 前端 — 轉錄佇列 active 子分頁排序與編號

- [x] 6.1 在 `src/QueueTab.jsx` active 子分頁 render 時，先把 rows 依 status 排序：所有 `running` 排在所有 `pending` 之前；同 status 內維持原 sort（屬「Admin page exposes a Transcription Queue tab」需求修訂中的「Active sub-tab shows running rows above pending rows with position numbers」scenario）
- [x] 6.2 移除 active 子分頁的「排隊中」/「執行中」section header（改純視覺排序，無 header）
- [x] 6.3 在每個 pending row 的最左側加一個 queue-position badge（圓圈或方框）顯示其 1-based ordinal（從 pending 段第一筆 = 1）
- [x] 6.4 running row 不顯示 position badge
- [x] 6.5 mobile 版同樣套用排序與 badge（對應「Active sub-tab on mobile」更新版）
- [x] 6.6 確認 drag-to-reorder 仍可用，且拖曳後 position badge 立即更新到新順序

## 7. 前端 — Empty-state 改導向

- [x] 7.1 修改 `src/PodcastSelect.jsx` 的空狀態：依 `user.role` 與 `user.status` 條件 render 不同 CTA（對應「Public PodcastSelect empty-state routes admins to admin show management」需求）
- [x] 7.2 admin 顯示「前往後台管理節目」按鈕，點擊呼叫 prop `setPage('admin-rag')`
- [x] 7.3 member / 未登入顯示「目前尚無節目，請聯絡管理員加入節目」雙語提示，無 button
- [x] 7.4 移除原本指向 `POST /shows` 的呼叫與相關 form
- [x] 7.5 在 `src/App.jsx` 把 `setPage` 與當前 user 透傳給 `PodcastSelect`
- [x] 7.6 在 `src/i18n.jsx` 加入兩個 string：`empty_shows_admin_cta` 與 `empty_shows_member_hint`，雙語

## 8. 驗證

- [x] 8.1 本地 docker compose 起 backend + 前端，跑 admin pytest 全套（含新 stats 測試）→ 全綠
- [x] 8.2 用瀏覽器測：admin 登入後到 Release Log 頁面，stats 區塊顯示 live 數字（with "live" 標籤）
- [x] 8.3 用瀏覽器測：member 帳號或登出狀態到 Release Log，stats 顯示 fallback 數字
- [x] 8.4 用瀏覽器測：時間軸版型在 desktop（>=768px）與 mobile（<768px）皆正確
- [x] 8.5 用瀏覽器測：佇列 active 子分頁顯示 running 在上、pending 在下、pending 帶 1/2/3 編號；拖曳 reorder 後編號跟著動
- [x] 8.6 用瀏覽器測：admin 在 PodcastSelect 看到「前往後台管理節目」按鈕；登出時看到 contact-admin 提示
- [x] 8.7 commit + push 觸發 Zeabur build；build 完成用 chrome-devtools-mcp 在 prod 重跑 8.2-8.6
