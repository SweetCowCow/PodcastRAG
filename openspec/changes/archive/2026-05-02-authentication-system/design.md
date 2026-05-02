## Context

PodcastRAG 目前完全沒有真實 auth：前端 `src/App.jsx:22` 用 `if (user === 'admin' && pass === '***REDACTED***')` 判斷登入，後端 `/admin/*` / `/queue/*` / `/schedules/*` / `/settings/*` / `POST /shows` / `DELETE /shows/{id}` 全部裸露。前後端跨 zeabur 子網域（`podcastrag.zeabur.app` ↔ `podcastrag-api.zeabur.app`）。LLM 走 Zeabur AI Hub 計費，query API 一旦對外公開，無 per-user cap 會被燒爆。

使用者明確要求：(1) 多人系統 (2) 嚴格正規作法 (3) Phase 1 只 gate 後台 + query (4) Google SSO 主登入 (5) 將來公開 repo (6) RBAC（一般人看查詢介面、admin 看後台）(7) 註冊 + 後台帳號管理頁要做。

技術約束：前端純 React 18 CDN + Babel Standalone（無打包），後端 FastAPI + PostgreSQL + Alembic + SQLAlchemy async。Zeabur deploy 為 single Dockerfile + entrypoint 切換。

## Goals / Non-Goals

**Goals:**

- 引入 Google OAuth 2.0 Authorization Code + PKCE 為唯一登入入口
- 用 httpOnly + Secure + SameSite=None session cookie 攜帶 session ID（opaque，存 Postgres `sessions` 表，登出可立即撤銷）
- Double-submit CSRF token 防跨站偽造請求
- `users` 表支援 RBAC（admin / member）、status（active / pending / disabled）、quota counters
- Bootstrap admin 透過 env `ADMIN_EMAILS` 白名單，登入時自動升級
- Open registration（A1）：未知 email 首次 Google 登入 → 自動建 active member + quota_initial=100
- Per-user query quota：`quota_remaining` 原子扣值，到 0 → 429；admin 後台手動加值（無自動補回）
- 後台「使用者管理」分頁：列表 + 搜尋 + role / status 編輯 + quota 加值 + 備註 + 刪除
- 後端 dependency `require_admin` / `require_authenticated_user` 統一 gate
- Phase 1 gate 範圍：所有 `/admin/*`、`/queue/*`、`/schedules/*`、`/settings/*`、`/shows` 寫入端、`/shows/{id}/sync`；以及 `/query`（要登入 + 扣 quota）
- 公開 repo 前用 `git filter-repo` 洗 history 中 `***REDACTED***` / `***REDACTED***`

**Non-Goals:**

- 全站 gate（首頁、節目選擇、逐字稿瀏覽未登入仍可看）— Phase 2
- Apple / GitHub / 本地密碼登入 — 未來
- Email magic link、密碼重設流程 — 不適用（純 SSO）
- Token refresh / silent refresh — 過期重登
- 自動每月 quota refresh / 計價系統 — 未來
- `SameSite=Lax` 部署 — 等買自有網域後另開 change（已記憶於 `project_custom_domain_plan.md`）
- 登入失敗 brute-force lockout — 因無本地密碼，Google 那端已有防護
- 個別 query 的 token / cost detail 紀錄 — 未來 usage analytics

## Decisions

### Google SSO 採 Authorization Code + PKCE

**選擇**：Backend-led OAuth flow。前端按「Sign in with Google」→ `GET /auth/google/start` 由後端產生 `state`（CSRF 用）+ `code_verifier`（PKCE）存入暫存 session（Redis 5min TTL），redirect 到 Google。Google 回 `GET /auth/google/callback?code&state` → 後端驗 state、用 code + verifier 換 token、抓 userinfo（email / name / picture / sub）→ upsert user → 建立 session row → set cookies → 302 回前端首頁。

**Why**：純前端 SPA OAuth 通常用 implicit / PKCE-only，但要把 client secret 暴露在 JS 才行，不夠正規。Backend-led 流程能保護 client secret + 集中驗 state + 直接寫 DB session。PKCE 仍保留是為了防 callback URL 在 log 中洩漏 code 被重放。

**Alternatives**：
- 純前端 PKCE flow → 前端要塞 GOOGLE_CLIENT_ID（OK，本來就是公開）+ exchange token endpoint 不需要 secret（用 PKCE 替代），但 user 資料拉取 / DB 寫入仍要打後端，等於前端拿到 ID token 後再 POST 給後端驗 → 多一個攻擊面（前端可能傳偽造 ID token，雖然能驗簽但流程更複雜）
- Authlib `starlette-client` 整合 → 簡化大量樣板碼。**採用**

### Session 機制用 opaque session ID + Postgres sessions 表

**選擇**：login 後產生 random 32-byte token → SHA256 hash 存 Postgres `sessions(id, user_id, csrf_token_hash, created_at, expires_at, last_seen_at, ip, user_agent)`；session cookie 內含 raw token（httpOnly + Secure + SameSite=None + Path=/ + Max-Age=14d）。

**Why**：
- 登出可即時撤銷（DELETE row）；JWT 要靠 blacklist
- 後台可看「目前活躍 session」，未來支援「登出所有裝置」
- Postgres 已有，不增依賴
- 14 天 sliding expiration（每次 request 更新 last_seen_at，超過 14 天無活動才過期）

**Alternatives**：
- JWT HS256 stateless → 簡單但撤銷難
- Redis session store → 更快，但本專案已用 Redis 做 Celery + throttle，混用 schema 易亂；Postgres 寫入頻率夠低（每 request 1 update）

### CSRF 用 double-submit token + Origin header check

**選擇**：login 時除了 session cookie，再 set 一個 `csrf_token` cookie（**非** httpOnly，JS 可讀，SameSite=None + Secure）。前端每次 state-changing request（POST/PUT/PATCH/DELETE）必須從 cookie 讀 csrf_token 放進 `X-CSRF-Token` header。後端 middleware：
1. GET / HEAD / OPTIONS 不檢查
2. 其他 method 驗 `X-CSRF-Token` header 存在 + 值等於 sessions 表的 csrf_token_hash 對應原文（用 constant-time compare）
3. 同步驗 `Origin` header 在 allowlist 內（`FRONTEND_ORIGIN` env）

**Why**：因 `*.zeabur.app` 在 PSL，cookie 必須 SameSite=None，失去 SameSite=Lax 這層便宜防禦。double-submit + Origin check 合起來等效防禦：攻擊者在 evil.com 因 Same-Origin Policy 讀不到 podcastrag.zeabur.app 的 cookie，無法偽造 X-CSRF-Token header。

**Alternatives**：
- Synchronizer token pattern（後端維護 server-side token map）→ 更嚴格但要每 request 查 DB；double-submit 只查 session 即可
- 只用 Origin check → 較弱，瀏覽器 bug 或舊 client 可能漏失

### CORS 收緊為 allowlist + credentials

**選擇**：後端 `CORSMiddleware` 從現行的開放（推測 `["*"]` 或寬鬆）改為：
- `allow_origins=[FRONTEND_ORIGIN]`（env 注入，prod 為 `https://podcastrag.zeabur.app`，dev 加 `http://localhost:3000`）
- `allow_credentials=True`
- `allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"]`
- `allow_headers=["Content-Type", "X-CSRF-Token"]`
- `expose_headers=[]`

**Why**：cookie auth 必須關閉 wildcard origin（CORS spec 要求）。這也順帶縮小公開 API 攻擊面。

### Bootstrap admin 用 env ADMIN_EMAILS 白名單

**選擇**：env `ADMIN_EMAILS=16249390+SweetCowCow@users.noreply.github.com,foo@bar.com`（comma-separated）。Google callback 處理 user upsert 時：
- 若 email in ADMIN_EMAILS → role=admin, status=active
- 否則 → role=member, status=active
- 若 user 已存在 → 不覆寫 role / status（admin 在後台手動改的權力優先）

**Why**：A1 open registration + 簡單。第一次部署不需 seed DB；要新增 admin 改 env + restart 即可，或在後台直接改 role。

### Quota 用 SQL 原子扣值，避免 race condition

**選擇**：`/query` endpoint 處理流程（async transaction）：
```
UPDATE users
SET quota_remaining = quota_remaining - 1,
    total_queries = total_queries + 1,
    last_seen_at = NOW()
WHERE id = :user_id AND quota_remaining > 0
RETURNING quota_remaining
```
若 0 row affected → 回 429 `quota_exhausted`（雙語錯誤，i18n key `error_quota_exhausted`）。若 1 row affected 才繼續打 RAG → 失敗時不退 quota（簡化，使用者重試會再扣，但成本端已實際發生）。

**Why**：純 ORM `user.quota_remaining -= 1; commit` 在並發下會 race（兩個 request 同時讀到 quota=1 都通過）。SQL atomic update 一行解決。

**Alternative**：Redis decrement + 定期 sync 回 DB → 更快但複雜，且 Redis crash 會丟 counter，本專案規模用不上。

### 失敗成本權衡 — query 後續失敗不退 quota

**選擇**：扣 quota 在 RAG 呼叫**前**做。若後續 OpenAI 429 / 網路掛掉 → quota 已扣，使用者可能覺得不公。

**Why**：(a) RAG 失敗大多是上游 transient，重試成功率高；退 quota 要再加一個 compensating transaction，code path 變複雜 (b) 真實 LLM cost 已支出（embedding 已查過、可能 partial token 已產出）(c) 量化：quota 預設 100，偶發 1 次失敗影響 1%。後台可手動加值補償。

**Mitigation**：admin 後台 quota 加值 endpoint 已有；錯誤訊息引導使用者「如為系統錯誤，請聯絡管理員加值」。

### Frontend 攜帶 credentials 與 CSRF token 的統一 fetch 包裝

**選擇**：新增 `src/AuthContext.jsx` 提供 `apiFetch(path, options)`：
- 自動 prepend backend base URL
- 預設 `credentials: 'include'`
- 從 `document.cookie` 讀 `csrf_token`，state-changing method 自動加 `X-CSRF-Token` header
- 401 → 清前端 user state，跳登入流程
- 429 + error_code=quota_exhausted → 觸發全域 toast

所有 `QueryPage.jsx` / `AdminPage.jsx` 等改用 `apiFetch` 取代 raw `fetch`。

**Why**：避免每個 component 重複處理 cookie / CSRF / 401，集中錯誤處理。

### User 列表分頁先不做

**選擇**：`GET /admin/users` 一次回全部（最多預期 < 1000 筆）。前端 `UserManagementTab.jsx` client-side filter / sort。

**Why**：YAGNI。少量宣傳階段使用者數很少。等突破 500 再加 server-side pagination + search。

### 公開 repo 前洗 git history 用 git filter-repo

**選擇**：在所有實作 + 部署驗證完成後，**最後**才執行：
```
git filter-repo --replace-text replacements.txt
```
`replacements.txt` 內容：
```
***REDACTED***==>***REDACTED***
***REDACTED***==>***REDACTED***
```
然後 force-push（**user 主動執行 + 確認**，Claude 不直接做 force push）。

**Why**：filter-repo 會改寫所有 commit hash，team 必須重新 clone。雖然只有使用者一人，仍視為「shared state 寫入」需明確確認。

**Risk**：Zeabur build 用 commit hash 可能 cache miss → 下次部署會 full rebuild（10min）。可接受。

## Risks / Trade-offs

- **[CSRF token via JS-readable cookie 看似矛盾]** → 這是 OWASP 認可的 double-submit pattern；XSS 拿到 csrf_token 沒用因為仍需 session cookie（httpOnly），雙重防線設計即假設 XSS 拿不到 session cookie
- **[`SameSite=None` 失去一層便宜防禦]** → 由 Origin check + CSRF token + CORS 三層補。買自有網域後切回 Lax（已記在 memory）
- **[Open registration 開放任何 Gmail 用戶建帳]** → quota_remaining=100 hard cap 控成本；admin 可在後台 disable 惡意帳號
- **[Quota 扣值在 RAG 之前]** → query 失敗仍扣，UX 不完美，但實作簡單；admin 加值補救
- **[Session cookie 在跨子網域要 SameSite=None]** → Safari ITP 對 third-party cookie 越來越嚴；本架構是 first-party（同 zeabur.app 上不同子域），不算 third-party，不影響。但 ITP 仍可能限制壽命。實測有問題再縮短 expires
- **[Bootstrap admin 靠 env restart]** → 第一次部署沒問題；後續新增 admin 偏好走後台 UI，env 只當底線
- **[git filter-repo 後使用者必須重新 clone]** → Claude 提示步驟 + 警示，使用者親自執行
- **[14 天 sliding session]** → 偷到 cookie 就最多 14 天有效；沒做 IP 變化偵測。可接受（單人或少人系統）
- **[後端 SECRET 增加]** → `GOOGLE_CLIENT_SECRET`、`SESSION_SECRET`（簽 cookie 用）、`ADMIN_EMAILS`、`FRONTEND_ORIGIN` 都進 backend/.env，Zeabur env 也要設

## Migration Plan

**Phase 0 — 本地開發（不影響 prod）**：
1. Alembic migration: 建 `users` 表 + `sessions` 表
2. 後端 auth router + middleware + dependency 完成
3. Google Cloud Console 建 OAuth client（dev redirect URI: `http://localhost:8000/auth/google/callback`）
4. 本地 backend/.env 補 OAuth + session env
5. 前端 AuthContext / apiFetch / login 流程接通
6. UserManagementTab 完成 + i18n
7. pytest 覆蓋 auth 流程 + quota 原子扣值 + CSRF 驗證

**Phase 1 — Zeabur 部署**：
1. Zeabur 後端 service 補 env：`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `SESSION_SECRET` / `ADMIN_EMAILS=16249390+SweetCowCow@users.noreply.github.com` / `FRONTEND_ORIGIN=https://podcastrag.zeabur.app`
2. Google OAuth client 加 prod redirect: `https://podcastrag-api.zeabur.app/auth/google/callback`
3. push → Zeabur 自動 build / deploy
4. 用 chrome-devtools-mcp 驗 prod login flow（含 admin email 自動升 role）+ quota 扣值 + 登出 + CSRF 攔截
5. 確認既有 `/query` 流程仍可用（綁 user 後）

**Phase 2 — 清 git history（最後做）**：
1. 確認 prod 與本地都已不依賴舊密碼字串
2. `git filter-repo --replace-text replacements.txt`（使用者親手執行）
3. `git push --force-with-lease origin main`（使用者親手執行）
4. 再次驗 Zeabur 部署沒爛

**Rollback 策略**：
- migration 有 down 函式，可 `alembic downgrade`
- 前端 hardcoded ***REDACTED*** 在 phase 1 中段才移除；若 phase 1 失敗，revert 該 commit 即可恢復原 modal 行為（因為 `/admin/*` gate 同時 revert，dependency 沒上線就無影響）
- git filter-repo 不可 rollback（已 force push），所以放最後

## Open Questions

- **Session 過期 14 天是否合理？** → 預設 14 天，使用者沒指定；實作時保留 env `SESSION_TTL_DAYS` 可調
- **Session table 是否要 cron 清過期 row？** → 是，但簡化做法：每次 login / logout 順手 DELETE expired；長尾留待 ops 階段
- **後台 user 列表預設排序？** → 建議 `last_login_at DESC`（活躍排前），admin 可切 created_at
- **/me 是否回 csrf_token？** → 不必，前端讀 cookie 即可；/me 只回 user data + quota
- **Quota=0 時前端該怎麼引導？** → 顯示 toast「查詢額度已用完，請聯絡管理員」+ 鎖 query input；細節留 implementation 決定
