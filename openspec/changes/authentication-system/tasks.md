## 1. 後端依賴與設定

- [x] 1.1 在 `backend/requirements.txt` 加入 `authlib`、`itsdangerous`、`httpx`（如尚未有），確認 SQLAlchemy 與 Alembic 版本支援 async + UUID/INET
- [x] 1.2 在 `backend/app/core/config.py` 新增 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`GOOGLE_REDIRECT_URI`、`SESSION_SECRET`、`ADMIN_EMAILS`、`FRONTEND_ORIGIN`、`SESSION_TTL_DAYS`（預設 14）等 pydantic-settings 欄位（對應「Authentication-related configuration via environment variables」需求）
- [x] 1.3 在 `backend/.env.example` 補齊上述變數的範例值與註解
- [x] 1.4 本地 `backend/.env` 寫入 dev 用 Google OAuth credentials 與 `FRONTEND_ORIGIN=http://localhost:3000`（人工確認後）

## 2. 資料庫 schema 與遷移

- [x] 2.1 建立 `backend/app/models/user.py` 對應 users table（id UUID、email、name、avatar_url、provider 預設 google、google_sub、role、status、total_queries、quota_remaining、quota_initial、notes、created_at、last_login_at）
- [x] 2.2 建立 `backend/app/models/session.py` 對應 sessions table（id、user_id FK CASCADE、session_token_hash、csrf_token_hash、created_at、expires_at、last_seen_at、ip、user_agent）
- [x] 2.3 撰寫 Alembic migration `XXXX_add_users_and_sessions_tables.py`：建 users + sessions 表、加 CHECK constraint（role / status）、unique index（email、google_sub、session_token_hash）；包含 down 函式
- [x] 2.4 在 dev 資料庫跑 `alembic upgrade head` 並驗證表結構（對應「users table」與「sessions table」需求）

## 3. Auth 核心服務

- [x] 3.1 建立 `backend/app/core/security.py`：random token 生成、SHA-256 hash 工具、constant-time compare（對應「Session 機制用 opaque session ID + Postgres sessions 表」決策）
- [x] 3.2 建立 `backend/app/services/google_oauth.py`：start flow 產 state + code_verifier + code_challenge S256；exchange_code(code, code_verifier)；fetch_userinfo(access_token)（對應「Google SSO 採 Authorization Code + PKCE」決策、「Google OAuth 2.0 login flow with PKCE」與「Google OAuth callback exchanges code, upserts user, creates session」需求）
- [x] 3.3 建立 `backend/app/services/user_service.py`：upsert_user_from_google(...) 處理 ADMIN_EMAILS 白名單升級邏輯（對應「Bootstrap admin 用 env ADMIN_EMAILS 白名單」決策）
- [x] 3.4 建立 `backend/app/services/session_service.py`：create_session(user_id, ip, ua)、resolve_session_from_cookie(session_id_value) 含 sliding expiration、delete_session(token)（對應「Session cookie carries opaque server-side session」需求 — httpOnly + Secure + SameSite=None + Max-Age=14d，server hashed token）
- [x] 3.5 建立 `backend/app/schemas/auth.py`、`backend/app/schemas/user.py`：定義 OAuth callback、UserOut、UserAdminOut、UserUpdate、QuotaPatch payload schemas

## 4. CSRF 與 Origin middleware

- [x] 4.1 建立 `backend/app/core/csrf.py`：CSRF token 生成、middleware class（對應「CSRF 用 double-submit token + Origin header check」決策、「CSRF token cookie protects state-changing requests」需求）
- [x] 4.2 在 middleware 中實作 Origin header 檢查邏輯（對應「Origin header is validated on state-changing requests」需求）
- [x] 4.3 將 CSRF/Origin middleware 註冊到 `backend/app/main.py`，順序在 CORS 之後、router include 之前

## 5. CORS 收緊

- [x] 5.1 修改 `backend/app/main.py` 的 `CORSMiddleware` 設定為 `allow_origins=settings.frontend_origin_list`、`allow_credentials=True`、`allow_methods` 限定常用 verbs、`allow_headers=["Content-Type", "X-CSRF-Token"]`，禁用 `*`（對應「CORS 收緊為 allowlist + credentials」決策、「FastAPI application entrypoint」需求修訂）
- [x] 5.2 確認 global exception handler 在 CORS middleware 之後仍能正確回應（測試 unhandled exception 帶 CORS header）

## 6. Auth Dependencies

- [x] 6.1 在 `backend/app/core/security.py` 新增 `require_authenticated_user` dependency：從 cookie 解析 session、驗有效、注入 User（對應「Authentication dependencies gate protected endpoints」需求）
- [x] 6.2 新增 `require_admin` dependency：基於 require_authenticated_user 進一步驗 role=admin + status=active

## 7. Auth API endpoints

- [x] 7.1 建立 `backend/app/api/auth.py` router：實作 `GET /auth/google/start`（對應「Google OAuth 2.0 login flow with PKCE」需求）
- [x] 7.2 在同 router 實作 `GET /auth/google/callback`：state 驗證、code exchange、upsert、create session、set cookies、302 回前端（對應「Google OAuth callback exchanges code, upserts user, creates session」需求）
- [x] 7.3 實作 `POST /auth/logout`（對應「Logout endpoint revokes session」需求）
- [x] 7.4 實作 `GET /me`：回傳目前使用者 + quota（對應「Current-user endpoint returns identity and quota」需求）
- [x] 7.5 在 `main.py` include auth router

## 8. 既有 endpoint 加 gate

- [x] 8.1 `backend/app/api/admin.py` router 加 `dependencies=[Depends(require_admin)]`
- [x] 8.2 `backend/app/api/queue.py` router 加 `require_admin`
- [x] 8.3 `backend/app/api/schedules.py` router 加 `require_admin`
- [x] 8.4 `backend/app/api/settings.py` router 加 `require_admin`
- [x] 8.5 `backend/app/api/shows.py` 個別 endpoint 加 gate：POST/DELETE/sync 加 `require_admin`；GET 維持公開
- [x] 8.6 確認 `episodes.py`、`transcripts.py`、`health.py` 維持公開（為 Phase 2 留空間）

## 9. Query endpoint 整合 quota（rag-query 修訂）

- [x] 9.1 修改 `backend/app/api/query.py` 加 `require_authenticated_user` dependency
- [x] 9.2 在 RAG 呼叫前加上 SQL 原子扣值 `UPDATE users SET quota_remaining = quota_remaining - 1, total_queries = total_queries + 1 WHERE id = :user_id AND quota_remaining > 0 RETURNING quota_remaining`（對應「Quota 用 SQL 原子扣值，避免 race condition」決策、「Query endpoint atomically decrements quota before invoking RAG」需求、「Semantic search endpoint returns ranked chunks」修訂）
- [x] 9.3 0 row affected → 回 HTTP 429 `quota_exhausted`（不呼叫任何 LLM API）
- [x] 9.4 在 query response 加上 updated quota_remaining 欄位
- [x] 9.5 處理「失敗成本權衡 — query 後續失敗不退 quota」決策：documenting in code comment、不實作 compensating refund（對應「Per-user query quota counters」需求中的 total_queries 永不減少）
- [x] 9.6 在 `backend/app/schemas/errors.py` 加 `quota_exhausted` 至 ErrorCode 常數

## 10. Admin 使用者管理 API

- [x] 10.1 建立 `backend/app/api/users.py` router 並 include 至 `main.py`
- [x] 10.2 `GET /admin/users`：回傳全部使用者（無分頁）（對應「User 列表分頁先不做」決策、「Admin user management tab lists all users」需求）
- [x] 10.3 `PATCH /admin/users/{id}`：支援更新 role / status / notes（對應「Admin can edit role, status, and notes per user」需求）
- [x] 10.4 `PATCH /admin/users/{id}/quota`：body `{delta}`，clamp `[0, 1_000_000]`（對應「Admin can adjust quota_remaining via top-up endpoint」需求）
- [x] 10.5 `DELETE /admin/users/{id}`：禁止刪除自己（後端二次驗證），cascade 刪 sessions

## 11. 後端測試

- [x] 11.1 撰寫 pytest 覆蓋 OAuth callback 流程（mock Google userinfo）：first-time member、ADMIN_EMAILS 升 admin、disabled 帳號擋掉、state mismatch
- [x] 11.2 撰寫 pytest 覆蓋 session sliding expiration + 過期 session 被拒
- [x] 11.3 撰寫 pytest 覆蓋 CSRF 中介層的攔截矩陣（GET 略過、POST 缺 header 擋、token 不符擋、Origin 不在 allowlist 擋）
- [x] 11.4 撰寫 pytest 覆蓋 quota atomic decrement 的並發情境（用 asyncio.gather 兩個 request 對 quota=1 的 user，預期一成功一 429）
- [x] 11.5 撰寫 pytest 覆蓋 `require_admin` 對 member / unauthenticated / disabled / pending 的拒絕

## 12. 前端 Auth Context 與 fetch 包裝

- [x] 12.1 建立 `src/AuthContext.jsx` 提供 `apiFetch(path, options)` 統一處理 credentials + CSRF header + 401 重導 + 429 quota toast（對應「Frontend 攜帶 credentials 與 CSRF token 的統一 fetch 包裝」決策）
- [x] 12.2 建立 `src/useCurrentUser.jsx` hook：mount 時打 `/me`、提供 `{user, loading, refresh, logout}` 介面
- [x] 12.3 在 `index.html` 引入新 jsx 檔案
- [x] 12.4 將 `src/QueryPage.jsx` 與 `src/AdminPage.jsx` 等所有打 backend 的 fetch 改用 `apiFetch`
- [x] 12.5 401 統一處理：清前端 user state 並顯示 toast 引導重新登入

## 13. 前端登入 / 登出 UI

- [x] 13.1 在 `src/App.jsx` 移除 hardcoded `***REDACTED***` 比對與 `AdminLogin` 元件呼叫（對應「Admin login modal SHALL NOT expose valid credentials in UI」修訂）
- [x] 13.2 刪除 `AdminLogin` 元件本身的程式碼（對應「Admin login modal SHALL keep its existing input and action affordances」REMOVED 需求 — 整個 username/password modal 移除，改用 Google SSO 按鈕）
- [x] 13.3 在 `src/Shared.jsx` 的 TopNav 新增「Sign in with Google / 使用 Google 登入」按鈕（未登入時顯示），點擊跳 `<BACKEND_BASE_URL>/auth/google/start`（對應「Top navigation provides Google sign-in entry point」需求）
- [x] 13.4 TopNav 已登入時顯示 avatar + name + 剩餘 quota + 登出按鈕（對應「Frontend displays current user info and remaining quota」需求）
- [x] 13.5 在 `src/App.jsx` 加 admin section guard：未登入 → 跳登入；member → 重導 `select`（對應「Admin section is gated by authenticated admin role」需求）

## 14. 後台使用者管理頁

- [x] 14.1 建立 `src/UserManagementTab.jsx`：列表 + 欄位（Avatar / Name / Email / Role / Status / Provider / Created / Last login / Total queries / Quota remaining / Notes / 操作）
- [x] 14.2 在 `AdminPage.jsx` 新增 `admin-users` route 與導覽 tab，僅 role=admin 可見
- [x] 14.3 實作 Edit modal：role / status / notes 編輯，PATCH 只送變更欄位（對應「Admin can edit role, status, and notes per user」需求）
- [x] 14.4 實作 Top up modal：numeric input、call `PATCH /admin/users/{id}/quota`、用回傳值更新 cell（對應「Admin can top up a user's remaining quota」需求）
- [x] 14.5 實作 Delete confirm + 自我刪除按鈕禁用 + tooltip（對應「Admin can delete a user」需求）
- [x] 14.6 在 `src/i18n.jsx` 加入 user management 表頭與按鈕雙語字串（對應「Bilingual labels in user management UI」需求）
- [x] 14.7 在 `src/i18n.jsx` 加入 `error_quota_exhausted`、`error_not_authenticated`、`error_csrf_token_*`、`error_account_disabled` 雙語錯誤訊息

## 15. Quota 顯示與封鎖

- [x] 15.1 TopNav 剩餘 quota 指標在 `quota_remaining=0` 改 danger 色
- [x] 15.2 `QueryPage.jsx` 偵測 `quota_remaining=0` 時 disable input 並顯示雙語提示「查詢額度已用完，請聯絡管理員」
- [x] 15.3 query 成功後從 response 同步更新前端 user state 的 quota_remaining（避免再打一次 /me）

## 16. 本地驗證

- [x] 16.1 在 Google Cloud Console 建立 OAuth 2.0 Client（Web type），加 `http://localhost:8000/auth/google/callback` 為 authorized redirect URI
- [x] 16.2 本地用 docker compose 起 backend + frontend，跑完整 login flow（含 admin email 自動升 role）
- [x] 16.3 手動測 quota 扣值（連打 query 看數字遞減）+ 達 0 後 429 + admin top-up 後可恢復查詢
- [x] 16.4 手動測 CSRF 防禦：用 curl 不帶 X-CSRF-Token 打 POST → 預期 403

## 17. Zeabur 部署

- [x] 17.1 在 Google Cloud Console OAuth client 加 prod redirect URI `https://podcastrag-api.zeabur.app/auth/google/callback`
- [x] 17.2 在 Zeabur backend service env 設定 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / SESSION_SECRET / ADMIN_EMAILS=16249390+SweetCowCow@users.noreply.github.com / FRONTEND_ORIGIN=https://podcastrag.zeabur.app / GOOGLE_REDIRECT_URI=https://podcastrag-api.zeabur.app/auth/google/callback
- [x] 17.3 push 觸發 Zeabur build，待 deploy 完成
- [x] 17.4 用 chrome-devtools-mcp 在 prod 完整跑：未登入 → 點登入 → Google 授權 → callback 回前端 → 看到 avatar + quota=100 → 進後台（admin email 應可進）→ 用 member 帳號試應被擋
- [x] 17.5 用 chrome-devtools-mcp 驗 prod query 扣 quota + 後台手動加值生效
- [x] 17.6 確認 prod 的既有功能（show 列表、轉錄序列、設定）仍正常

## 18. 公開 repo 前清理（最後步驟）

- [x] 18.1 確認 prod 與本地都不再依賴舊密碼字串
- [x] 18.2 撰寫 `replacements.txt`（內容：`***REDACTED***==>***REDACTED***` 與 `***REDACTED***==>***REDACTED***`）（對應「公開 repo 前洗 git history 用 git filter-repo」決策）
- [x] 18.3 由使用者親自執行 `git filter-repo --replace-text replacements.txt` 並警示後果（須重新 clone）
- [x] 18.4 由使用者親自 `git push --force-with-lease origin main`
- [x] 18.5 觸發 Zeabur 重新 build，驗證 prod 仍正常運作
