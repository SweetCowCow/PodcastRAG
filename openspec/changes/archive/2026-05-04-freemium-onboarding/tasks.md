## 1. Settings 與環境變數（對應「Per-user query quota counters」與 ip-rate-limit / quota-request-flow 的 settings 需求）

- [x] 1.1 在 `backend/app/core/config.py` 加 4 個 settings：`default_user_quota: int = 30`、`ip_search_rate_limit_per_day: int = 20`、`zsend_api_key: str | None = None`、`zsend_from_email: str | None = None`、`zsend_admin_to_email: str | None = None`，docstring 各說明用途
- [x] 1.2 在 `backend/tests/test_config.py` 加 case 驗 `default_user_quota` 預設 30、env `DEFAULT_USER_QUOTA=50` 覆寫成功
- [x] 1.3 在 `backend/tests/test_config.py` 加 case 驗 `ip_search_rate_limit_per_day` 預設 20 + env 覆寫
- [x] 1.4 更新 `backend/.env.example`（若存在）+ 部署文件說明 4 個新 env 變數

## 2. quota_requests 表與 Model（對應「Quota requests table tracks user-submitted quota top-up applications」需求）

- [x] 2.1 新增 `backend/app/models/quota_request.py`：定義 `QuotaRequestStatus` enum（pending/approved/rejected）、`QuotaRequest` SQLAlchemy model，欄位完全對應 spec（id UUID PK、user_id FK CASCADE、reason Text、status enum default pending、granted_amount Int nullable、rejection_note Text nullable、requested_at TIMESTAMPTZ default now、processed_at nullable、processed_by FK nullable、last_digest_at nullable）；加 `relationship` 到 `User`
- [x] 2.2 在 `backend/app/models/__init__.py` 匯出 `QuotaRequest`、`QuotaRequestStatus`
- [x] 2.3 在 `backend/app/models/user.py` 加 `quota_requests: Mapped[list[QuotaRequest]] = relationship(back_populates='user', cascade='all, delete-orphan')` （若 user.py 結構合適；否則就跳過 relationship 直接靠 FK）
- [x] 2.4 撰寫 alembic migration `backend/alembic/versions/<rev>_add_quota_requests.py`：CREATE TYPE quota_request_status_enum + CREATE TABLE + 兩個 indexes（status+last_digest_at、user_id+requested_at desc）；downgrade drop 全部
- [x] 2.5 本機跑 `alembic upgrade head`，psql 確認表 + 欄位 + indexes 都建立、enum 存在

## 3. Pydantic schemas（對應 quota_requests endpoints 的 request/response 結構）

- [x] 3.1 新增 `backend/app/schemas/quota_request.py`：`QuotaRequestCreate(reason: str = Field(min_length=10, max_length=1000))`、`QuotaRequestOut`（id, status, reason, requested_at, processed_at, granted_amount, rejection_note）、`QuotaRequestAdminOut`（extends Out + user_email + user_quota_remaining + processed_by 等 admin 才看的欄位）、`QuotaApprove(amount: int = Field(ge=1, le=1_000_000))`、`QuotaReject(note: str = Field(min_length=1, max_length=1000))`

## 4. ZSend client（對應「Beat scheduled task digests pending quota requests to admin email」內 ZSend HTTP 呼叫部分）

- [x] 4.1 新增 `backend/app/services/zsend.py`：定義 `async def send_email(to: str, subject: str, body_text: str)`，用 `httpx.AsyncClient` 打 ZSend send endpoint（base url 與 path 從 ZSend docs 確認；Bearer auth header 用 `settings.zsend_api_key`），timeout 30s，raise on non-2xx
- [x] 4.2 加最簡 `ZSendError` exception class，映射 4xx 為 client error（不重試）、5xx + timeout 為 retryable
- [x] 4.3 在 `backend/tests/test_zsend_client.py` 用 `httpx.MockTransport` 建立 fake response，測 200 成功、500 raise、422 raise + 含 ZSend 回應 detail；確認 Authorization header 帶 Bearer token

## 5. IP rate limit helper（對應「Per-IP daily rate limit on public search endpoint」需求）

- [x] 5.1 新增 `backend/app/core/rate_limit.py`：`def _client_ip(request: Request) -> str`（讀 X-Forwarded-For 第一段，fallback `request.client.host`）、`async def check_ip_search_limit(redis: aioredis.Redis, ip: str, limit: int) -> tuple[int, bool]`（INCR + 第一次 EXPIRE 86400；回傳 (current_count, exceeded)）
- [x] 5.2 從既有 `backend/app/workers/throttle.py` 或其他 redis client 模組複用 redis 連線；若無共用 helper 就在這裡建一個 `get_redis_client()` 工廠
- [x] 5.3 撰寫 `backend/tests/test_ip_rate_limit.py`：mock redis（`fakeredis`），測首次 INCR=1 + EXPIRE 設定、第 N 次仍允許、第 N+1 次拒絕、跨 UTC midnight key 切換

## 6. optional_auth_with_ip_limit dependency（對應「Authentication dependencies gate protected endpoints」需求修訂）

- [x] 6.1 在 `backend/app/core/security.py`（或既有 auth dependency 集中位置）加 `async def optional_auth_with_ip_limit(request, db) -> User | None`：先嘗試 `_resolve_session(request, db)`；若 active user 直接 return；若無 session 走 IP rate limit；若超出 raise `HTTPException(429, detail={"error_code":"ip_rate_limited", "limit":limit, "reset_at_utc":...})`
- [x] 6.2 確認 dependency 不影響 expired session 的清理邏輯（既有 `_resolve_session` 該怎麼清就怎麼清；過期的 session 視為無 session）
- [x] 6.3 在 `backend/tests/test_auth_csrf.py` 或新增 `test_optional_auth.py` 加 case：(a) 帶有效 session → 回 user、redis counter 不動；(b) 無 session 且 counter 5/20 → 回 None、counter 變 6；(c) 無 session 且 counter 20/20 → raise 429；(d) 帶過期 session cookie → fall through 走 IP path

## 7. Public search endpoint（對應 rag-query「Semantic search endpoint returns ranked chunks」需求修訂）

- [x] 7.1 在 `backend/app/api/query.py` 新增 `POST /shows/{show_id}/search` route，guarded by `optional_auth_with_ip_limit`；body 用新 schema `SegmentSearchRequest(question: str, k: int = Field(default=8, ge=1, le=50))`
- [x] 7.2 endpoint 不論 user 是 None 還是已登入，都跑 embedding + pgvector 查詢，回 top-K 段落（複用既有的 search 邏輯但**不**減 quota）；response schema `SegmentSearchResponse(results: list[ChunkOut])`，**不**含 answer 欄位
- [x] 7.3 把既有 `POST /shows/{show_id}/query` 改成只接 `mode='chat'`（或乾脆移除 mode 參數），維持 `require_authenticated_user` + 原子 quota decrement；若舊 frontend 還會送 `mode=search` 進來就回 400 提示路徑變更（過渡 1 個 release 後可移除提示）
- [x] 7.4 撰寫 `backend/tests/test_public_search.py`：(a) 匿名 + IP 5/20 → 200 + 回段落 + counter 6；(b) 匿名 + IP 滿 → 429 ip_rate_limited、無 embedding call（mock）；(c) 已登入 + IP 滿 → 200，counter 不動，quota 不動；(d) 跨 show 過濾正確；(e) k 超過 50 自動 clamp
- [x] 7.5 撰寫測試確認舊 `POST /shows/{show_id}/query` 仍要登入 + 仍會減 quota（既有 case 應仍綠；若有預期失敗，調 fixture）

## 8. Quota requests user endpoints（對應「User can submit one pending quota request at a time」與「User can view their own quota request history」需求）

- [x] 8.1 新增 `backend/app/api/quota_requests.py`：FastAPI router prefix `/quota-requests`，三個 endpoint：`POST /` (require_authenticated_user, body `QuotaRequestCreate`)、`GET /me` (require_authenticated_user, optional `?status=` query)、若想要 `GET /me/{id}` 則加（非必要）
- [x] 8.2 `POST /` 實作：先 `SELECT 1 FROM quota_requests WHERE user_id=? AND status='pending'`，已存在 → raise 409 `error_code='quota_request_pending'`；否則 INSERT row，回 HTTP 201
- [x] 8.3 `GET /me` 實作：`SELECT * FROM quota_requests WHERE user_id=:uid [AND status=:status] ORDER BY requested_at DESC`
- [x] 8.4 在 `backend/app/main.py` 註冊 router
- [x] 8.5 撰寫 `backend/tests/test_quota_requests_api.py`：4 個 case 對應 spec scenarios（first 201、second 409、reason 太短 422、processed 後可再送）+ GET /me 過濾正確

## 9. Quota requests admin endpoints（對應「Admin can list and process quota requests」需求）

- [x] 9.1 新增 `backend/app/api/admin/quota_requests.py`：router prefix `/admin/quota-requests`，guarded by `require_admin`；`GET /` (optional `?status=`)、`POST /{id}/approve` (body `{"amount": int}`)、`POST /{id}/reject` (body `{"note": str}`)
- [x] 9.2 `GET /` join users 表把 `email` + `quota_remaining` 一起回；order by `requested_at ASC`（pending 從舊到新給 admin 處理）
- [x] 9.3 `POST /{id}/approve` 用 `SELECT ... FOR UPDATE` 鎖 row、檢查 `status='pending'`；非 pending → 409 `already_processed`；否則同 transaction 裡 UPDATE row + UPDATE users.quota_remaining（用 `LEAST(quota_remaining + :amount, 1_000_000)` clamp）；回應含 `quota_remaining`、`request_id`、`status`
- [x] 9.4 `POST /{id}/reject` 同樣 FOR UPDATE 檢查 + UPDATE row 為 rejected + processed_*；不動 user.quota_remaining
- [x] 9.5 在 `backend/app/main.py` 註冊 admin router
- [x] 9.6 撰寫 `backend/tests/test_quota_requests_admin.py`：6 個 case（approve 加 quota + 標 processed、reject 不動 quota + 標 processed、already_processed 409、approve clamp 到 1M、admin role gate（member 收 403）、unauthenticated 401）

## 10. Beat 排程：digest task（對應「Beat scheduled task digests pending quota requests to admin email」需求）

- [x] 10.1 新增 `backend/app/workers/quota_digest.py`：`@celery_app.task(name='app.workers.quota_digest.send_quota_digest', autoretry_for=(httpx.HTTPError, httpx.TimeoutException), max_retries=2, retry_backoff=True)` `def send_quota_digest()`；body 跑 `_run()` 用 asyncio.run
- [x] 10.2 `_run()` 流程：(a) SELECT pending rows where last_digest_at IS NULL OR < now()-INTERVAL '6 hours'；(b) 若 0 row log info 並 return；(c) 組 plain-text body（每筆 user email + reason + requested_at ISO + 等多久 + footer link `https://podcastrag.zeabur.app/admin/quota-requests`）；(d) parse `settings.zsend_admin_to_email` 為逗號分隔 email list；(e) 對每位收件人 await `zsend.send_email`；(f) UPDATE last_digest_at = now() 給剛才所有 row id
- [x] 10.3 在 `backend/app/workers/celery_app.py` `beat_schedule` 加 entry：`'quota-digest': {'task': 'app.workers.quota_digest.send_quota_digest', 'schedule': crontab(minute=0, hour='9,21')}`
- [x] 10.4 撰寫 `backend/tests/test_quota_digest_task.py`：(a) 3 pending rows last_digest_at NULL + 2 收件人 → ZSend mock 被呼叫 2 次、3 row 都 update last_digest_at；(b) 1 row last_digest_at=now-30min + 1 row NULL → 只算 1 row、ZSend 內容只列 1 筆、只有 1 row 被 update；(c) 0 pending → ZSend 不被呼叫；(d) ZSend 第一次 503 → autoretry，最終成功就只寄 1 次

## 11. Auth callback：default quota from setting（對應 auth-system「Google OAuth callback exchanges code, upserts user, creates session」與 user-quota「Per-user query quota counters」需求修訂）

- [x] 11.1 在 `backend/app/api/auth.py` Google callback 寫入新使用者的地方，把硬編碼 `quota_remaining=100, quota_initial=100` 改成讀 `settings.default_user_quota`
- [x] 11.2 `backend/tests/test_auth_db.py` 新加 case：`monkeypatch.setenv('DEFAULT_USER_QUOTA', '50')` + 觸發 first-time 登入 → user 有 quota_remaining=50、quota_initial=50；驗 既有 user U1 quota 不會被 env 改影響

## 12. Frontend：LandingPage 元件（對應 landing-page 全部需求 + frontend-responsive-layout「Landing Page is responsive」需求）

- [x] 12.1 新增 `src/LandingPage.jsx`：root container + 三段：Hero、Collected Shows、Paywall band；最上面 TopNav（重用 Shared.jsx `<TopNav>`）+ 右上角 `<Btn variant='ghost' size='sm'>登入</Btn>`
- [x] 12.2 Hero 區：H1 + H2（用 lang 切換）、`<Input>` 搜尋框（placeholder per spec）、CTA `<Btn variant='primary'>找回靈光一閃</Btn>`；desktop 同列 + mobile 換行（用 useViewport hook）
- [x] 12.3 Hero 搜尋邏輯：onSubmit 直接 `setPage('select')` 並把 query 寫入既有的 query state 或 URL param；空字串就只 navigate（不報錯）
- [x] 12.4 Collected Shows 區：`useEffect` GET `/shows`，render 卡片 grid（desktop 3-col、mobile 1-col；用 inline style + useViewport）；卡片內容：title、description（zh 截 60 / en 截 100 + `…`）、總集數、轉錄完成度（從 episodes API 推算或新增 public stats endpoint；先簡單用 `/shows` 回傳的 episode_count）、`[瀏覽集數 →] <Btn>`；點擊把 `selectedShow` 設好並切到 query 頁
- [x] 12.5 Paywall band：`💎` 圖示 + 標題（per spec 文案）+ 兩行 body + `<Btn variant='primary'>以 Google 登入 →</Btn>` 觸發既有 `<LoginModal>`；視覺上水平 max-width 720px、置中
- [x] 12.6 在 `src/App.jsx` 路由分支：未登入 + `page === 'select'`（root 路由）→ render LandingPage 而非 PodcastSelect；登入後則維持 PodcastSelect；refresh-while-logged-in 不能 flash LandingPage（用「等 /me resolved 再決定 render 哪個」+ 中間 loading state）
- [x] 12.7 在 `index.html` 引入 `src/LandingPage.jsx`
- [x] 12.8 用 chrome-devtools-mcp 在本機 dev 開 / desktop（1280×800）+ mobile（375×667）兩個視窗，hard refresh 不會 flash、登入後不再 render Landing、所有文案中英切換正確

## 13. Frontend：QueryPage 雙層體驗（對應「QueryPage shows quota meter and unlock card states」需求）

- [x] 13.1 在 `src/QueryPage.jsx` 上方狀態列：認證使用者 render `<QuotaMeter quota_remaining={u.quota_remaining} quota_initial={u.quota_initial} onApply={openModal} />`，匿名使用者 render null
- [x] 13.2 拆既有 query call：原 `POST /shows/{id}/query` `mode=search` → 改成新 `POST /shows/{id}/search`（不需 csrf 因為非 state-changing? 確認後端是否要 CSRF；既有 csrf middleware 對 GET 不檢查、POST 才檢查；search 是 POST → 仍需 CSRF；匿名使用者**沒 csrf cookie**怎辦？方案：search endpoint 從 csrf middleware exempt list 加進去，或改為 GET）；做出最終決定並實作
- [x] 13.3 確認後端 `csrf.py` middleware 對 `/shows/.+/search` 跳過 CSRF（IP rate limit + 不改 state、純讀取，安全 OK）；補測試 `backend/tests/test_public_search.py` case：匿名無 csrf cookie 仍能成功
- [x] 13.4 LLM 答案區：認證 → 既有行為（call `/query` chat endpoint）；匿名 → 不 call `/query`，直接 render `<LockedAnswerCard>` 元件（內嵌在 QueryPage 內定義）
- [x] 13.5 `<LockedAnswerCard>`：高度上限 200px、圖示 🔒、文案 per spec、`<Btn variant='primary'>以 Google 登入解鎖</Btn>` + 下方 secondary text `30 次免費`；按鈕觸發既有 LoginModal
- [x] 13.6 LoginModal 成功 callback 後 re-resolve auth state（既有 useAuth hook 應已處理）+ Locked card 自動消失 + 自動觸發既有 LLM 答案 call

## 14. Frontend：QuotaMeter + QuotaApplyModal（對應「QuotaApplyModal collects and submits quota request」需求 + frontend QueryPage quota meter 部分）

- [x] 14.1 新增 `src/QuotaMeter.jsx`：水平進度條（`background-color` 漸層或 `<progress>` 標準元素）顯示 `已用 X / 共 Y`、進度比例 `(initial - remaining) / initial`、右側 `<Btn size='sm' variant='ghost'>申請更多額度 →</Btn>`；無條件顯示按鈕（不擋門檻）
- [x] 14.2 新增 `src/QuotaApplyModal.jsx`：`<Modal>` 內含 heading + textarea (`minLength=10 maxLength=1000`) + submit / cancel buttons；open 時先 `GET /quota-requests/me?status=pending`；若有 pending → 替換成 blocked state（顯示送出於 X、僅 close 按鈕）；submit 時 POST `/quota-requests` body `{reason}`、201 → 顯示成功訊息 ~2 秒後 `onClose()`、409 → 切到 blocked state、422 → 顯示 inline error
- [x] 14.3 在 `index.html` 引入兩個新檔
- [x] 14.4 chrome-devtools-mcp 驗證：(a) modal 開啟 → 預設空 textarea；(b) 已有 pending 時不顯示 textarea；(c) 送出成功訊息出現後關閉；(d) 短於 10 字 inline 錯誤

## 15. Frontend：AdminPage Quota 申請 sub-tab（對應「Admin Quota Requests sub-tab」+「Admin can approve」+「Admin can reject」需求）

- [x] 15.1 在 `src/AdminPage.jsx` 既有 Users tab 結構下，加新子 tab `Quota 申請`；對應 `page === 'admin-quota-requests'` 路由值
- [x] 15.2 子元件 `<QuotaRequestsTab>`：fetch `GET /admin/quota-requests?status=<filter>`；status filter chip（pending / approved / rejected）；table 欄位：requester email、reason（截斷+hover tooltip）、requested_at（相對時間 like `3 小時前`）、目前 quota_remaining、action area
- [x] 15.3 Action area for pending rows：inline `<input type='number' min=1 max=1000 default=30>` + `<Btn>核准 +N</Btn>`（label 隨 input 變動）+ secondary `<Btn>拒絕</Btn>`
- [x] 15.4 核准 click → POST `/admin/quota-requests/{id}/approve` `{amount}`；200 → 從 listing 移除 row + toast「已核准」；409 → toast 「此申請已被處理」+ refetch
- [x] 15.5 拒絕 click → 開小 confirmation `<Modal>` 含 textarea (minLength=1) + confirm；confirm → POST `/admin/quota-requests/{id}/reject` `{note}`；200 → 從 listing 移除
- [x] 15.6 Tab label 旁邊紅色 badge：fetch pending count（可獨立 polling 或 reuse listing 結果）；> 0 才顯示
- [x] 15.7 Admin 路由註冊：`'admin-quota-requests'` 加進 App.jsx 的 admin pages 清單；左側 nav 加項目（重用既有 admin nav 結構）
- [x] 15.8 chrome-devtools-mcp prod 驗證：點 Quota 申請 tab、看到 pending list、approve 一筆 → 對應 user quota 增加；reject 一筆 → quota 不動、row 消失

## 16. 部署：階段 A 後端基建 commit + push

- [x] 16.1 階段 A 包含 tasks 1-11（後端全部 + auth callback 改動），不含 frontend；本機跑 `pytest backend/tests/` 全綠
- [x] 16.2 commit + push；4 個 service redeploy；entrypoint 自動 alembic upgrade head
- [x] 16.3 prod 驗 1（curl + e2e-login）：新 endpoint `/shows/{show_id}/search` 已存在；匿名打 `POST /shows/{id}/search?question=test` 不被 401（IP limit 內 200 + 段落）
- [x] 16.4 prod 驗 2：`POST /quota-requests` 帶 session 能成功送出 pending；admin GET `/admin/quota-requests` 看得到
- [x] 16.5 prod 驗 3：在 Zeabur 4 service 設好 5 個新 env（DEFAULT_USER_QUOTA、IP_SEARCH_RATE_LIMIT_PER_DAY、ZSEND_API_KEY、ZSEND_FROM_EMAIL、ZSEND_ADMIN_TO_EMAIL）；觀察 startup log 沒有 missing env warning
- [x] 16.6 確認舊 frontend（v0.9）仍可正常運作（既有 query 仍登入後可用）

## 17. 部署：階段 B 前端 freemium UI commit + push

- [x] 17.1 階段 B 包含 tasks 12-14（LandingPage / QueryPage 雙層 / QuotaMeter / QuotaApplyModal）
- [x] 17.2 本機 dev server 起來，chrome-devtools-mcp 跑完 task 12.8 + 14.4 的所有驗證 case
- [x] 17.3 commit + push；frontend redeploy
- [x] 17.4 prod 驗（chrome-devtools-mcp）：(a) 開 incognito 進首頁 → 看到 LandingPage 不是 select 頁；(b) 點熱門節目卡片 → 進 QueryPage、看到段落、看到 LockedAnswerCard；(c) 點解鎖 → LoginModal 開、Google 登入、自動回到 QueryPage、答案出現；(d) 已登入使用者直接進 / → render PodcastSelect 不 flash Landing；(e) QuotaMeter 顯示 `0 / 30 已用` + 申請按鈕；(f) 開申請 modal → 送出 → toast → 後台看得到 pending row

## 18. 部署：階段 C Admin tab + Beat 排程 commit + push

- [x] 18.1 階段 C 包含 task 15（AdminPage Quota 申請 tab）
- [x] 18.2 commit + push frontend；無 backend 改動但既有 `/admin/quota-requests` 已在階段 A 上線
- [x] 18.3 prod 驗：admin 登入後台 → 點 Quota 申請 tab → 看到 pending count badge、approve 一筆測試申請（自己送的就好）→ user quota 增加、row 從 pending 移除
- [x] 18.4 等下個 cron 觸發點（UTC 9:00 或 21:00）後檢查 ZSend 是否寄出彙整 email；或手動觸發 `celery -A app.workers.celery_app call app.workers.quota_digest.send_quota_digest` 提早驗證

## 19. Archive 後維護（per memory dual-write rule）

- [x] 19.1 archive 後更新 `docs/roadmap.md`：U1 標 ✅ 完成（form changed from「全站登入 gate」to「freemium 分層 gate」）
- [x] 19.2 同步更新 `project_pending_changes.md`（最近 archive、下次開場 briefing）
- [x] 19.3 起草 v1.0 release log entry：tag=`feature`、milestone=`v1.0`，標題「公開上線：freemium 模式」、文案描述未登入可瀏覽 + 搜尋段落、登入解鎖 AI 答案、30 次免費額度、申請補充流程

## 20. Coverage 索引（讓 analyzer 確認每個 requirement / design topic 都有對應 task；無實作行）

實際對應關係：

- [x] (cov) 對應 「Per-user query quota counters」需求修訂 → 1.1（settings 改 default 30）+ 11.1（callback 讀 setting）+ 11.2（test）
- [x] (cov) 對應 「Quota requests table tracks user-submitted quota top-up applications」需求 → 2.1, 2.2, 2.3, 2.4, 2.5
- [x] (cov) 對應 「User can submit one pending quota request at a time」需求 → 3.1, 8.1, 8.2, 8.4, 8.5
- [x] (cov) 對應 「User can view their own quota request history」需求 → 3.1, 8.1, 8.3, 8.5
- [x] (cov) 對應 「Admin can list and process quota requests」需求 → 3.1, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
- [x] (cov) 對應 「Beat scheduled task digests pending quota requests to admin email」需求 → 4.1, 4.2, 4.3, 10.1, 10.2, 10.3, 10.4, 18.4
- [x] (cov) 對應 「Per-IP daily rate limit on public search endpoint」需求 → 1.3, 5.1, 5.2, 5.3
- [x] (cov) 對應 「optional_auth_with_ip_limit FastAPI dependency」需求 → 6.1, 6.2, 6.3
- [x] (cov) 對應 「Landing Page renders for unauthenticated visitors at site root」需求 → 12.6, 12.8
- [x] (cov) 對應 「Landing Page hero presents copy and primary CTA」需求 → 12.1, 12.2, 12.3, 12.8
- [x] (cov) 對應 「Landing Page lists collected shows with real data」需求 → 12.4
- [x] (cov) 對應 「Landing Page paywall band explains the freemium boundary and offers login」需求 → 12.5
- [x] (cov) 對應 「Landing Page top navigation includes secondary login button」需求 → 12.1
- [x] (cov) 對應 「Google OAuth callback exchanges code, upserts user, creates session」需求修訂 → 11.1, 11.2
- [x] (cov) 對應 「Authentication dependencies gate protected endpoints」需求修訂 → 6.1, 6.2, 6.3
- [x] (cov) 對應 「Query endpoint atomically decrements quota before invoking RAG」需求修訂 → 7.3, 7.5
- [x] (cov) 對應 「Semantic search endpoint returns ranked chunks」需求修訂 → 7.1, 7.2, 7.4, 13.2, 13.3
- [x] (cov) 對應 「Chat endpoint answers with citations using Tier 2 RAG」需求修訂 → 7.3, 7.5
- [x] (cov) 對應 「Landing Page is responsive between mobile and desktop」需求 → 12.2, 12.4, 12.6, 12.8
- [x] (cov) 對應 「QueryPage shows quota meter and unlock card states」需求 → 13.1, 13.4, 13.5, 13.6, 14.1
- [x] (cov) 對應 「QuotaApplyModal collects and submits quota request」需求 → 14.2, 14.3, 14.4
- [x] (cov) 對應 「Admin Quota Requests sub-tab lists pending and processed quota_requests」需求 → 15.1, 15.2, 15.6, 15.7
- [x] (cov) 對應 「Admin can approve a quota request inline with an amount」需求 → 15.3, 15.4
- [x] (cov) 對應 「Admin can reject a quota request with a note」需求 → 15.3, 15.5

設計決策對應：

- [x] (cov) D1：段落搜尋 endpoint 設計 → 7.1, 7.2, 7.3
- [x] (cov) D2：IP Rate Limit 實作 → 5.1, 5.2, 5.3
- [x] (cov) D3：optional_auth dependency 與 LLM endpoint 互動 → 6.1, 6.2, 6.3, 13.4
- [x] (cov) D4：quota_requests 表設計 → 2.1, 2.4, 10.2
- [x] (cov) D5：Quota 申請反濫用 → 8.2, 14.2
- [x] (cov) D6：ZSend 彙整 email 內容格式 → 4.1, 10.2
- [x] (cov) D7：Beat 排程觸發頻率 → 10.3
- [x] (cov) D8：Landing Page vs select 頁的關係 → 12.6
- [x] (cov) D9：QueryPage quota meter 與「申請更多額度」按鈕 → 13.1, 14.1
- [x] (cov) R1：免登入搜尋的 embedding 成本上限 → 5.3, 16.5
- [x] (cov) R2：Quota 申請濫用（一個使用者送 100 個 pending）→ 8.2
- [x] (cov) R3：ZSend 服務中斷 → 10.1, 15.6
- [x] (cov) R4：跨 session 實作的併發風險 → 16.1, 17.1, 18.1
- [x] (cov) R5：QueryPage 鎖定卡片的視覺優先級 → 13.5
- [x] (cov) R6：`users.status='pending'` 列舉值仍保留 → 11.1
