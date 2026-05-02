## Why

目前後台帳密 `admin / admin999` 寫死在前端 `src/App.jsx:22`，任何看到原始碼的人都能登入；後端 `/admin/*` endpoints 完全沒有 auth gate，知道 URL 就能直接呼叫。這個安全債阻擋 GitHub repo 公開、阻擋分享給外部試用者，且使用者開放外部試用後 LLM 額度沒有 per-user 上限會被燒爆。本 change 建立正規多人帳號驗證系統，導入 Google SSO + RBAC + 查詢次數 quota，為後續公開做準備。

## What Changes

- **新增 `users` 表**：欄位 id / email / name / avatar_url / provider / google_sub / role / status / total_queries / quota_remaining / quota_initial / notes / created_at / last_login_at
- **新增 Google OAuth 2.0 Authorization Code + PKCE 登入流程**：`/auth/google/start`、`/auth/google/callback`、`/auth/logout`、`/me`
- **Session 機制**：httpOnly + Secure + SameSite=None session cookie；double-submit CSRF token（非 httpOnly cookie + `X-CSRF-Token` header）；CORS allowlist + Origin header 檢查
- **RBAC**：role = `admin` / `member`；status = `active` / `pending` / `disabled`（A1 open registration → 預設新人 member + active）
- **Bootstrap admin 機制**：env `ADMIN_EMAILS` 白名單，符合 email 透過 Google 登入後自動升 admin
- **Per-user query quota**：`quota_remaining` 預設 100，每次 query 成功原子扣 1，到 0 → 429 `quota_exhausted`；`total_queries` lifetime 累計，永不歸零
- **後端 auth gate**：`/admin/*`、`/queue/*`、`/schedules/*`、`/settings/*` 加 `require_admin` dependency；`/shows` POST/DELETE/sync 加 admin gate；`/query` 加 `require_authenticated_user` 且綁 quota；GET `/shows`、`/episodes/*`、`/transcripts/*`、`/health` 維持公開（為 Phase 2 全站 gate 留空間）
- **前端**：移除 `AdminLogin` 內 hardcoded `admin999` 判斷 → 改打 `/auth/google/start` 跳轉；新增 `useCurrentUser` hook 從 `/me` 拉資料；右上角顯示登入狀態 + 剩餘 quota；後台新增「使用者管理」tab（欄位：Avatar / Name / Email / Role / Status / Provider / Created / Last login / Total queries / Quota remaining / Notes / 操作）
- **後台使用者管理 API**：`GET /admin/users`、`PATCH /admin/users/{id}`（改 role / status / notes）、`PATCH /admin/users/{id}/quota`（`{delta}` 加值）、`DELETE /admin/users/{id}`
- **公開 repo 前清理**：用 `git filter-repo` 從 history 移除 `admin123` / `admin999` 字串

## Non-Goals

- **全站登入 gate**：本 change 只 gate 後台 + query API；首頁、節目選擇、查詢介面（未登入仍可瀏覽）、逐字稿留待未來 change（Phase 2）
- **每月 quota 自動補回 / 點數計價系統**：本次只做硬性 cap + admin 手動加值；自動補額 / 計價留未來 change
- **多 SSO provider**：只串 Google；Apple / GitHub / 本地密碼登入留未來
- **Email magic link / 密碼登入**：完全跳過自管密碼流程，僅透過 Google
- **Token refresh / remember me**：session 過期就重登，不做 silent refresh
- **`SameSite=Lax` 防禦**：因 `*.zeabur.app` 預期在 PSL，必須 `SameSite=None`，等買自有網域後另開 change 切回 Lax
- **使用量統計 dashboard**：個別 user 的 query 紀錄 detail（時間、token、成本），本次只做 counter；分析 dashboard 留未來

## Capabilities

### New Capabilities

- `auth-system`: Google OAuth 2.0 PKCE 登入流程、session cookie + CSRF、users 表 schema、`/auth/*` 與 `/me` endpoints、bootstrap admin 白名單機制
- `user-quota`: per-user 查詢次數限制機制；`total_queries` lifetime counter、`quota_remaining` 可扣值額度、原子扣值與 429 錯誤、admin 加值 endpoint
- `admin-user-management-ui`: 後台「使用者管理」分頁 UI（列表、role/status 編輯、quota 加值、備註、刪除）

### Modified Capabilities

- `db-schema`: 新增 `users` 表 requirement
- `backend-core`: 新增 auth middleware / `require_admin` 與 `require_authenticated_user` dependency requirement、CORS credentialed origins、CSRF 驗證
- `rag-query`: query endpoint 改為需登入 + 綁 user quota（成功扣 1、達 0 回 429）
- `admin-login-modal-ui`: 移除示範密碼判斷，改為 Google SSO 跳轉按鈕

## Impact

- Affected specs:
  - New: `openspec/specs/auth-system/spec.md`、`openspec/specs/user-quota/spec.md`、`openspec/specs/admin-user-management-ui/spec.md`
  - Modified: `openspec/specs/db-schema/spec.md`、`openspec/specs/backend-core/spec.md`、`openspec/specs/rag-query/spec.md`、`openspec/specs/admin-login-modal-ui/spec.md`
- Affected code:
  - New:
    - backend/app/models/user.py
    - backend/app/api/auth.py
    - backend/app/api/users.py
    - backend/app/core/security.py
    - backend/app/core/csrf.py
    - backend/app/services/google_oauth.py
    - backend/app/services/user_service.py
    - backend/app/schemas/auth.py
    - backend/app/schemas/user.py
    - backend/alembic/versions/XXXX_add_users_table.py
    - src/UserManagementTab.jsx
    - src/useCurrentUser.jsx
    - src/AuthContext.jsx
  - Modified:
    - backend/app/main.py（include auth router、CORS allow_credentials、Origin middleware、global CSRF middleware）
    - backend/app/api/admin.py、queue.py、schedules.py、settings.py、shows.py（加 require_admin dependency）
    - backend/app/api/query.py（加 require_authenticated_user + quota 扣值）
    - backend/app/core/config.py（新增 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / SESSION_SECRET / ADMIN_EMAILS / FRONTEND_ORIGIN env）
    - backend/requirements.txt（新增 authlib、itsdangerous、bcrypt 等）
    - src/App.jsx（移除 hardcoded admin999、改用 AuthContext、admin 進入前驗 role）
    - src/AdminPage.jsx（新增 users tab）
    - src/QueryPage.jsx（fetch 帶 credentials + CSRF header、429 錯誤處理）
    - src/Shared.jsx（TopNav 顯示登入狀態 + quota）
    - src/i18n.jsx（auth / quota 雙語訊息）
    - backend/.env.example（新增 OAuth 與 session env）
  - Removed:
    - 無檔案級刪除；僅移除 `src/App.jsx` 內 hardcoded admin/admin999 判斷邏輯
- 公開 repo 前操作（不在程式碼變更中，列為 task）：執行 git filter-repo 洗 history
