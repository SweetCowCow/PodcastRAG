## Context

PodcastRAG 目前是 **Phase 1 gate**：未登入訪客被擋在 select / query / transcript 之外，只能看 Landing 跳到 Google 登入。對外公開的轉換率會嚴重不足 — 第一次來訪的人連節目列表都看不到，無法評估這個工具是否有用就被要求登入。

既有架構（authentication-system change archive）：
- Google SSO + RBAC（admin / member）+ session cookie + CSRF 三層；env `ADMIN_EMAILS` 白名單第一次登入自動 admin
- `users.status` enum 已有 pending / active / banned；登入時若 status=pending 會 raise
- `user_quota.quota_remaining` 寫死 default 100（從 authentication-system migration 帶入）
- 路線圖原 U1 想做 pending / approval queue / email 驗證 — 本 change **取消**這條路，改 freemium

新架構分歧：
- **段落搜尋 vs LLM 答案** 分屬兩個 endpoint；前者免登入但走 IP rate limit，後者要登入 + quota
- **quota 不自動補回**，靠使用者主動「申請更多額度」+ admin 後台手動處理
- ZSend 整合用於彙整通知 admin（不是即時發信）

## Goals / Non-Goals

**Goals:**

- Landing Page 和 select / query 變成「先看到價值再要登入」的 freemium 流程
- 段落搜尋（top-K）對未登入訪客開放，靠 IP rate limit 控成本上限
- LLM 答案維持登入 + quota gate，quota 用完不自動補回
- 註冊流程零摩擦：Google SSO 一鍵 → 立即 active，無 pending、無 email 驗證
- 使用者可主動申請更多 quota，admin 收彙整 email 後到後台處理
- 既有 LoginModal 元件可重用，多個入口指向同一個 modal

**Non-Goals:**

- 點數計價 / 付費購買（U2）
- 自動每月 quota 補回（U2）
- email 驗證流程（freemium 開放任何 google 帳號註冊）
- Bypass admin SSO（仍走 Google + ADMIN_EMAILS 白名單）
- 替代 email provider（先綁 ZSend）
- A/B 測試 Landing 文案（第一版固定文案）

## Decisions

### D1：段落搜尋 endpoint 設計

**選項：**
- A. 單一 `/query` endpoint，body 加 `include_answer: bool`，後端依登入狀態自動降級
- B. **拆兩個 endpoint：`/query/search`（公開）+ `/query` 或 `/query/answer`（限登入）**
- C. 同一 endpoint 視 cookie 自動切換，return 結構不同

**選 B**。理由：
- 兩個 endpoint 的 auth dependency 不同（B1 用 optional_auth_with_ip_limit，B2 用 require_authenticated_user），FastAPI 寫法乾淨
- response 結構不同（公開版只有 sources，登入版多 answer + sources），分開就不用 `Optional[str]` 難以 OpenAPI doc
- 前端可獨立 retry 任一 call（網路不穩時 search 已成功就不用重 LLM）

### D2：IP Rate Limit 實作

**選項：**
- A. fastapi-limiter 套件
- B. **自寫 Redis counter（INCR + EXPIRE）**
- C. nginx / Zeabur layer 限制

**選 B**。理由：
- fastapi-limiter 帶 SlowAPI / Redis-py 額外依賴；既有專案已有 `redis-py`（Celery broker），重用即可
- 邏輯極簡：key = `rl:search:ip:{ip}:{YYYYMMDD}`；INCR 後若 == 1 設 EXPIRE 86400；INCR 後若 > limit 拒絕
- IP 取值用 `request.headers.get('x-forwarded-for', request.client.host)`（取第一個 IP，Zeabur proxy 會帶 XFF）
- 拒絕時 raise 429，body `{"error_code": "ip_rate_limited", "detail": "已達今日免費搜尋上限，請登入繼續使用", "limit": N, "reset_at_utc": "YYYY-MM-DDT00:00:00Z"}`

### D3：optional_auth dependency 與 LLM endpoint 互動

新 dependency `optional_auth_with_ip_limit` 行為：
1. 嘗試 resolve session：cookie session_id 有效 → 回 User
2. 無 session：抓 IP，做 Redis INCR：
   - 未超 → 回 None（caller 用 `Optional[User]` 接）
   - 已超 → raise 429

`/query/search` 用此 dependency；其 `current_user: User | None`。`/query`（LLM 答案）用既有 `require_authenticated_user`，未登入直接 401 — 前端會渲染鎖定卡片，不會打這個 endpoint。

**安全考量：**
- 已登入使用者不受 IP rate limit 影響（session 解析優先）
- 未登入但有 cookie session 過期 → 走 IP path（一致行為）

### D4：quota_requests 表設計

```
CREATE TABLE quota_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  reason TEXT NOT NULL,
  status quota_request_status_enum NOT NULL DEFAULT 'pending',
  granted_amount INTEGER,                       -- approve 才填，reject = NULL
  rejection_note TEXT,                          -- reject 才填
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ,                     -- approve / reject 時間
  processed_by UUID REFERENCES users(id),       -- 哪個 admin
  last_digest_at TIMESTAMPTZ                    -- 上次被彙整 email 包含的時間
);
CREATE INDEX ON quota_requests (status, last_digest_at);
CREATE INDEX ON quota_requests (user_id, requested_at DESC);
```

**Why `last_digest_at`**：
- 不能單純 SELECT WHERE status='pending'，因為使用者今天送、明天又送一筆，admin 還沒處理；09:00 + 21:00 兩次彙整不該重複包含同一筆
- 寄完 email 後 batch update `last_digest_at = now()` 在剛才 SELECT 出的 row。下次 task 跑撈條件 `last_digest_at IS NULL OR last_digest_at < now() - INTERVAL '6 hours'`
- 6h 是因為兩次 digest 間 12h，留半個週期 buffer 防 cron drift / 暫時延遲；確保「沒處理就重新提醒」
- admin approve / reject 後 status 改變，自然不會再進 SELECT

### D5：Quota 申請反濫用

選項：
- A. **限制每位使用者同時最多 1 筆 status='pending' 的申請**
- B. 任意送，admin 篩
- C. 每使用者每 N 天最多送 1 筆

**選 A**。理由：
- 一個使用者反覆送一樣的 reason 對 admin 是雜訊
- 後端 `POST /quota-requests` check：`SELECT 1 FROM quota_requests WHERE user_id=? AND status='pending'`，已存在 → 回 409 `{"error_code": "quota_request_pending"}`
- 前端：modal 開啟前先 GET `/quota-requests/me?status=pending` 看是否已有 → 已有則直接顯示「您已有一筆審核中的申請（送出於 YYYY-MM-DD）」訊息，不顯示 textarea

### D6：ZSend 彙整 email 內容格式

- Plain text（不用 HTML — 簡化、避免 ZSend HTML 限制）
- Subject：`[PodcastRAG] {N} 筆 quota 申請待處理`
- Body：列出每筆 reason、user email、requested_at、最舊那筆等多久；附上 admin URL `https://podcastrag.zeabur.app/admin/quota-requests`
- 多收件人：`zsend_admin_to_email` 支援逗號分隔，task 拆成多個 to_email 一一寄（ZSend API 一次一封）
- 失敗 retry：autoretry_for `(httpx.HTTPError, httpx.TimeoutException)` max_retries=2 backoff=60s；最終失敗 log error 不影響其他 task；不 mark `last_digest_at`，下次 12h 重試

### D7：Beat 排程觸發頻率

cron `0 9,21 * * *` UTC = 台北時間 17:00 + 隔日 05:00。

**Trade-off**：原本想 09:00 台北時間（UTC 01:00）+ 21:00 台北（UTC 13:00），但開發者深夜睡覺收 email 體感差。改 17:00 台北（下班前）+ 隔日 05:00（早上起床順便看）對 admin 行為較合理；且 UTC 09:00 / 21:00 在 cron expression 上是整數小時，cron 字串簡潔。

**可調**：cron 寫死在 celery_app.py 的 beat_schedule，後續若要動態調再說。

### D8：Landing Page vs select 頁的關係

| 路由 | 未登入 | 已登入 |
|------|--------|--------|
| `/` | LandingPage | redirect to `/select` 或直接 render select |
| `/select` | PodcastSelect（公開）| PodcastSelect |
| `/query/{show_id}` | QueryPage（公開、雙層）| QueryPage（unlock）|
| `/transcript/{episode_id}` | TranscriptPage（公開）| TranscriptPage |
| `/admin/*` | redirect to `/` + 顯示 LoginModal（既有行為）| 後台 |

LandingPage 是 React 元件而非 SSR；客戶端判斷 cookie 有 session 就 mount select，否則 mount LandingPage。實作上在 App.jsx 既有 page state 機制下加 `landing` 路由值。

### D9：QueryPage quota meter 與「申請更多額度」按鈕

- meter 顯示：`AI 額度：▓▓▓▓▓▓░░░░ 18/30 已用` — 用 quota_initial - quota_remaining 計算「已用」
- 「申請更多額度」按鈕無條件顯示（即使 quota 充足），點下 modal
- meter 對未登入使用者**不顯示**（避免雜訊）
- meter 數據來源：`/me` endpoint 已 return `quota_remaining`、`quota_initial`，不需新 API

## Risks / Trade-offs

### R1：免登入搜尋的 embedding 成本上限

最差情境：1000 個獨立 IP 每天打滿 20 次 = 20K embedding calls/day = $0.4/day = ~$12/month。可接受。
若被 botnet 大量 IP 輪流攻擊：理論上限取決於 IP 多寡。**緩解**：未來可加 fingerprint（user-agent + IP）或要求 captcha；現階段不做。

### R2：Quota 申請濫用（一個使用者送 100 個 pending）

D5 已限制每使用者同時 1 筆 pending。若使用者連續 reject 後馬上送新的，會塞爆 admin → reject 後加 `cooldown` 機制？暫時不做（reject 是手動操作，admin 篩掉壞使用者就好）；若實際上線發現問題再 followup。

### R3：ZSend 服務中斷

ZSend 掛掉時 admin 不會收彙整 email，pending 申請 stack 起來。**緩解**：admin 後台 Quota 申請 tab 仍能看到所有 pending（不靠 email），email 只是 push 通知。Tab 旁邊加紅色 badge 顯示 `pending count`，admin 進後台即看到。

### R4：跨 session 實作的併發風險

規模 ~60 tasks 大概率跨 2-3 sessions。風險：中途 commit 導致 prod 暫時處於「半 freemium」狀態（前端已開放但後端尚未拆 endpoint）。**緩解**：分階段實作 + 每階段 deploy 都是可運行狀態：
1. **階段 A — 後端基建**（DB migration + ZSend client + rate limit + endpoint 拆分 + 新 settings）：deploy 後 prod 仍是舊行為（前端尚未變），但新 endpoints 已存在
2. **階段 B — 前端 freemium UI**（LandingPage / QueryPage 雙層 / quota meter / apply modal）：deploy 後 freemium 體驗上線
3. **階段 C — Admin Quota tab + Beat 排程**（後台 UI + scheduled email）：deploy 後完成全套

每階段都單獨 commit + push，不卡前後依賴。

### R5：QueryPage 鎖定卡片的視覺優先級

設計上 LLM 答案區在 sources 上方（既有 layout）。如果未登入時鎖定卡片擋住整個答案區會讓段落區被推下去 → 使用者要捲動才看到段落。**選擇**：鎖定卡片高度限制（最多 200px），段落區仍在 viewport 內出現。或反向：sources 移到上、locked card 移到下 — 但這會打亂登入後的閱讀順序。**選**前者（高度限制）。

### R6：`users.status='pending'` 列舉值仍保留

D 區塊提到不再有 pending 自動入口，但既有 `users.status` enum 包含 pending，且 require_authenticated_user 會 raise pending 使用者。保留是為了未來 admin 可主動 ban → 必要時 reset 為 pending（人工流程）。本 change 不修 enum。
