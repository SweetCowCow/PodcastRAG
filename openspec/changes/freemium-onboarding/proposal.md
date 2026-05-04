## Why

目前 PodcastRAG 對未登入使用者完全擋住 select / query / transcript（**Phase 1 gate**），第一次來的人連節目列表都看不到，無法評估這個工具是否有用就被要求登入。對外公開後這會嚴重傷害轉換率。**Freemium 是解法**：把瀏覽 + 看相關段落（無 LLM 成本）開放給未登入訪客，把 LLM 統整回答（有 cost）鎖在登入後。同時把註冊流程簡化到極致（Google 一鍵 → 立即 active），quota 用完讓使用者主動「申請更多額度」而不是自動補回，避免免費刷量。

這個 change 也奠定 U1（路線圖原本叫「全站登入 gate」）的最終形態 — 不是 gate 全部，而是分層 gate。

## What Changes

- **(A) Landing Page 改寫**：`/`（未登入時）顯示新文案。H1：「那個來賓說過什麼？」別再瘋狂快轉了。 H2：忘記在哪一集沒關係。直接問，從節目片段中找回那道遺忘的靈光一閃，瞬間解開你的疑惑。 主 CTA：「找回靈光一閃」（按下捲到搜尋框 / 直接 focus）。主搜尋框 placeholder：「例如：在 這又沒有很屌 查詢『歌單』」。下方顯示三張真實節目卡片（曼報 139 集 / 壹加壹電台 252 集 / 這又沒有很屌 162 集），各帶轉錄完成度進度條（從 `/admin/stats` 推估或新增 public endpoint）。底部 paywall band：「💎 30 次 AI 統整回答（一次性免費額度，用完可申請補充）」+「以 Google 登入」按鈕。右上角次要登入按鈕。
- **(B) 段落搜尋免登入 + IP rate limit**：拆分 query API：原 `/query` endpoint 改為「LLM 統整回答」端點仍要登入。新增 `/query/search` endpoint 只回 top-K 段落（不過 LLM），允許未登入；用 Redis counter 做每 IP 每天 N 次（預設 `IP_SEARCH_RATE_LIMIT_PER_DAY=20`），超過回 429 + `error_code='ip_rate_limited'` 並提示登入。Search 仍會吃 embedding 成本（~$0.00002/次）但天花板可控。
- **(C) QueryPage 雙層體驗**：未登入時 LLM 答案區 render 鎖定卡片「想看 AI 整段統整？／不用一段段拼湊。／[以 Google 登入解鎖]／30 次免費」；段落區照常顯示。登入後 LLM 答案區自動 unlock。
- **(D) 註冊流程簡化**：捨棄路線圖原 U1 中的 pending / approval queue / email 驗證概念。Google SSO 成功 → 後端把新使用者 status 直接設 `active`，配 `default_user_quota=30`（env 可調）。ADMIN_EMAILS 白名單第一次登入仍自動 promote 為 admin。`users.status='pending'` 列舉值保留以防 admin 主動 ban → reset 流程，但**不再**有自動 pending 入口。
- **(E) Quota 申請流程**：新表 `quota_requests`（id, user_id FK, requested_at, reason text, status enum[pending/approved/rejected], processed_at, processed_by FK users, granted_amount int nullable）。新 endpoint：`POST /quota-requests`（登入需 quota（即使 0 也允許）、寫 row、retn 200）；admin `GET /admin/quota-requests?status=`、`POST /admin/quota-requests/{id}/approve {amount: int}`、`POST /admin/quota-requests/{id}/reject {note: str}`。前端 QueryPage 上方狀態列**無條件**顯示 quota meter + 「申請更多額度」button（即使 quota 還很多也顯示，使用者要主動點才會出現 modal）。Modal 是 textarea 填用途（最少 10 字元，避免空送）。
- **(F) ZSend 整合 + Beat 排程彙整**：新 settings `zsend_api_key`、`zsend_from_email`、`zsend_admin_to_email`（後者可設多個逗號分隔）。Beat 加新排程 entry `digest_quota_requests`，cron `0 9 * * *` 與 `0 21 * * *` 兩次（UTC 09:00 + 21:00 = 台北 17:00 + 隔日 05:00；可調 cron 式）。task 撈 status='pending' AND processed_at IS NULL 的所有列、依 created_at asc 列出，組成一封 plain text email 經 ZSend HTTP API 寄出（不寄個別 email；不修改 status — admin approve / reject 才改）。若 ZSend 回非 2xx，log error + 不重試（下次 12 小時後再試彙整新增的 + 還沒被處理的舊請求。已被 email 過的不會被重複統計，靠 admin 處理掉就消失）。為避免重複寄送同一 pending 請求，加欄位 `last_digest_at` (timestamptz nullable)，task 只撈 `last_digest_at IS NULL OR last_digest_at < now() - INTERVAL '6 hours'` 的列；寄出後批次 update last_digest_at。
- **(G) Admin 後台 Quota 申請 tab**：`AdminPage.jsx` Users tab 既有架構下加子 tab「Quota 申請」（路由 `admin-quota-requests`）。表格顯示 user email + reason + requested_at + 「approve {amount}」inline 表單 + 「reject」button。Approve 走 `quota_remaining += amount`，把該 quota_request 標 `approved` + `processed_by` + `granted_amount`，reject 同理。
- **(H) 新 settings**：`default_user_quota: int = 30`、`ip_search_rate_limit_per_day: int = 20`、`zsend_api_key: str | None`、`zsend_from_email: str | None`、`zsend_admin_to_email: str | None`。
- **(I) Auth dependency**：新增 `optional_auth_with_ip_limit` FastAPI dependency。如果 cookie 帶有效 session → 回 user。如果無 session → 走 IP rate limit check：未超 → 回 None（搜尋 endpoint 自行處理「無 user 時不需 quota check」）；超出 → raise 429。LLM 答案 endpoint 不變，繼續用 `require_authenticated_user`。
- **(J) Frontend：登入 Modal 進入點多元化**：Landing 主 CTA、Landing 右上角、Landing 底部、QueryPage 解鎖卡片、QueryPage 「申請更多額度」… 全部觸發既有 `LoginModal`（authentication-system 已建好），不重做。

## Non-Goals

- **不**做 quota 自動補回（U2 的責任）
- **不**做點數計價 / 付費購買（U2 的責任）
- **不**做 email 驗證流程（freemium 開放任何 google 帳號）
- **不**做帳號 ban / unban UI（既有 `users.status` enum 已有 `banned`、admin 後台 Users tab 既有架構未來可加）
- **不**改 transcript 頁的 gate（已是免登入；本 change 不動）
- **不**改 admin 後台 query usage stats 邏輯（U3 的責任）
- **不**整合 SendGrid / Resend / SES 等替代 email provider（先綁 ZSend，未來抽象再說）
- **不**做整集對話入口（A5）、混合檢索（R3）、RAG cache（R4）— 路線圖另排

## Capabilities

### New Capabilities

- `quota-request-flow`: 使用者送 quota 申請、admin 後台處理、Beat 每 12 小時彙整 email 通知 admin 的整套流程。包含 DB schema、API endpoints、admin UI、scheduled email digest。
- `ip-rate-limit`: 未登入訪客的搜尋 endpoint 用 Redis counter 做 per-IP daily rate limit；超過回 429 + 結構化 error_code。
- `landing-page`: 公開 Landing Page 的版面、文案、CTA、節目卡片區、登入區。獨立於 select 頁（select 頁仍是登入 / 未登入皆可進入瀏覽，但登入後直接跳 select）。

### Modified Capabilities

- `auth-system`: 新使用者註冊預設 status=`active` 而非 `pending`；新增 optional_auth_with_ip_limit dependency；ADMIN_EMAILS 自動 promote 邏輯不變。
- `user-quota`: 新 setting `default_user_quota` 取代寫死的 100；新 endpoint `POST /quota-requests`；user 模型加關聯到 quota_requests。
- `rag-query`: 拆 endpoint：`/query` 改為登入限定（保持 LLM 答案功能）；新增 `/query/search` 公開 endpoint（純 top-K 段落、不過 LLM）。前端 QueryPage 改造成雙層體驗。
- `frontend-responsive-layout`: Landing Page 加入新 layout（Hero + 節目卡片 grid + paywall band），需確保 mobile breakpoint < 768 仍可讀；QueryPage 加 quota meter 狀態列 + 鎖定卡片，影響既有 layout 高度。
- `admin-user-management-ui`: Users 頁新增「Quota 申請」子 tab。

## Impact

- Affected specs: `quota-request-flow`(new), `ip-rate-limit`(new), `landing-page`(new), `auth-system`, `user-quota`, `rag-query`, `frontend-responsive-layout`, `admin-user-management-ui`
- Affected code:
  - New:
    - `backend/alembic/versions/<rev>_add_quota_requests.py`
    - `backend/app/models/quota_request.py`
    - `backend/app/schemas/quota_request.py`
    - `backend/app/api/quota_requests.py` (使用者 endpoint)
    - `backend/app/api/admin/quota_requests.py` (admin endpoints)
    - `backend/app/core/rate_limit.py` (Redis counter helper)
    - `backend/app/core/auth_deps.py` 內新增 `optional_auth_with_ip_limit`（檔案視既有 dependency 集中位置決定，可能放在 `backend/app/core/security.py`）
    - `backend/app/services/zsend.py` (HTTP client wrapper)
    - `backend/app/workers/quota_digest.py` (Celery task 寄彙整 email)
    - `backend/tests/test_quota_requests_api.py`
    - `backend/tests/test_quota_requests_admin.py`
    - `backend/tests/test_ip_rate_limit.py`
    - `backend/tests/test_zsend_client.py`
    - `backend/tests/test_quota_digest_task.py`
    - `src/LandingPage.jsx` (新元件，App 路由分支用)
    - `src/QuotaApplyModal.jsx` (申請額度彈窗)
    - `src/QuotaMeter.jsx` (進度列 + 申請按鈕，可重用 in QueryPage 上方)
  - Modified:
    - `backend/app/api/auth.py` (Google callback：新使用者 status=active + default quota)
    - `backend/app/api/query.py` (拆 endpoints：`/query` LLM 限登入、`/query/search` 公開帶 IP limit)
    - `backend/app/services/session_service.py` 或 `backend/app/core/security.py` (新 dependency)
    - `backend/app/core/config.py` (新 settings)
    - `backend/app/workers/celery_app.py` (Beat schedule entry: digest_quota_requests)
    - `backend/app/main.py` (註冊新 router)
    - `backend/app/models/user.py` (若需要 relationship 到 quota_requests)
    - `src/App.jsx` (路由：未登入 `/` → LandingPage；已登入 `/` → 既有 select)
    - `src/QueryPage.jsx` (鎖定卡片、quota meter 整合)
    - `src/AdminPage.jsx` (Users 頁加 Quota 申請子 tab)
    - `src/PodcastSelect.jsx` (確認未登入仍可瀏覽)
    - `src/TranscriptPage.jsx` (確認未登入仍可瀏覽)
    - `src/Shared.jsx` (若 LoginModal 需新 prop 接受 callback / context-aware copy)
    - `index.html` (引入新 .jsx 檔)
  - Removed: (none)
- 部署影響：4 個 service（backend / worker / dispatcher / beat）皆要 redeploy。Frontend 也要 redeploy。Beat schedule 新增一個 entry 會自動載入。
- Env 新增（4 個 service 都要設）：
  - `DEFAULT_USER_QUOTA=30`
  - `IP_SEARCH_RATE_LIMIT_PER_DAY=20`
  - `ZSEND_API_KEY=<key>`
  - `ZSEND_FROM_EMAIL=noreply@yourdomain` (或 ZSend default)
  - `ZSEND_ADMIN_TO_EMAIL=16249390+SweetCowCow@users.noreply.github.com` (彙整收件人)
- 成本：embedding cost 上限可控（每 IP 每天 20 次 × $0.00002 = $0.0004/IP/day）；ZSend 每天最多 2 封彙整 email，遠低於免費額度。
- 規模：~58-65 tasks，跨層（DB / Backend / Worker / Frontend / Admin UI）。**建議分 backend → frontend → polish 三階段做**，避免一次 commit 太大。
