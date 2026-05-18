## Context

`backend/app/api/auth.py` 既有的 Google OAuth callback 在使用者 email 命中黑名單時 raise 403 `ACCOUNT_DISABLED`。前端 `src/App.jsx` 收到 callback 失敗目前只顯示 generic error，Lock card 第三狀態（disabled）也尚未實作（Lock card 拍版時 anonymous + quota exhausted 兩態先做、disabled 拉出本 change）。既有 `quota_requests` 表與 `quota_digest.py` worker 已驗證可行（POST endpoint + 表 + 每日 admin email digest），本 change 沿用相同模式。

## Goals / Non-Goals

**Goals**
- 被停權使用者能在 Lock card 內提交申訴（事由 + 自動帶 email）
- Admin 每日收到 digest email 列出當天新申訴，可手動回覆並調整黑名單
- 申訴資料持久化於 DB，方便日後回查與後台 UI 介接
- 不要求 admin 立即看後台（MVP 走 email + DB 直查）

**Non-Goals**
- Admin 後台審核介面（後續 follow-up change）
- 通知申訴人結果（人工 email 回覆即可）
- 防濫用：除每 email/IP rate limit 外不做 CAPTCHA
- 附件上傳

## Decisions

- **Endpoint 不放 `/quota-requests` 之下**：申訴與額度申請語意不同（disabled vs quota），且 disabled user 在 callback 階段就被拒、根本沒 session，需公開（unauthenticated）endpoint；`POST /auth/appeal` 接受 email + reason，由後端比對 `users.disabled` 才接受。
- **沿用 quota digest worker 模式**：新建 sibling `appeal_digest.py`（不混進 `quota_digest.py` 以保 cohesion），同樣 Celery beat 排程（每日台北 9:00）。
- **`account_appeals` 表獨立、不複用 `quota_requests`**：兩者欄位語意不同（quota_requests 要 quota 數字，appeal 要 reason text + disabled_at 快照），共表會把 nullable 欄位炸開。
- **`appeal_enabled: true` 旗標放在 403 response body**：不靠前端硬編 `ACCOUNT_DISABLED` → 顯示申訴入口；讓後端日後可關閉申訴（例如重大濫用事件）。
- **Rate limit 沿用 `ip_rate_limit`**：同 IP 每日最多 5 次申訴，避免 spam。

## Implementation Contract

**Observable behaviors**

1. `POST /auth/appeal` 接受 `{ email: str, reason: str (1-2000 chars) }`，回 `{ accepted: true, appeal_id: uuid }`；錯誤情境：
   - email 不在 `users` 表或 `users.disabled = false` → 200 `{ accepted: true }`（不洩漏帳號存在性，沉默 dropped）
   - reason 空白或 >2000 字 → 400 `INVALID_REASON`
   - 同 IP 當日 >5 次 → 429 `RATE_LIMITED`
2. 403 `ACCOUNT_DISABLED` response body 從 `{ error: "ACCOUNT_DISABLED" }` 改為 `{ error: "ACCOUNT_DISABLED", appeal_enabled: true }`。
3. 前端 `App.jsx` 收 callback 403 + `appeal_enabled=true` → render Lock card disabled 狀態（🚫 icon + 「提出申訴」按鈕）→ 開 `AppealModal`。
4. `appeal_digest` Celery task 每日 09:00 台北時間排程：query `account_appeals.created_at >= 24h ago` 並 email `ADMIN_EMAILS`；空清單時 skip 不寄。

**Data shape**

`account_appeals` 表：
- `id` UUID PK
- `email` TEXT NOT NULL
- `reason` TEXT NOT NULL
- `client_ip` TEXT NULLABLE（rate limit 用）
- `user_disabled_at_snapshot` TIMESTAMPTZ NULLABLE（記錄當時 user 黑名單時間）
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT now()
- `notified_at` TIMESTAMPTZ NULLABLE（digest 寄出時間，避免重寄）
- INDEX on `created_at`, `email`

**Acceptance criteria（自動驗證）**

- `backend/tests/api/test_appeal.py` 涵蓋 4 個情境：accepted / silent-drop（非 disabled email）/ INVALID_REASON / RATE_LIMITED
- `backend/tests/workers/test_appeal_digest.py` 涵蓋空清單 skip + 有資料時 email 寄出 + `notified_at` 寫回
- 手動驗證：prod 模擬黑名單帳號登入 → Lock card disabled 顯示 → 送出申訴 → admin email 收到 digest

**Scope boundaries**

- 範圍內：endpoint + 表 + migration + Lock card disabled state UI + AppealModal + appeal_digest worker + 4 個 test 檔
- 範圍外：admin 後台 UI、通知申訴人結果、appeal status 工作流（pending/approved/rejected）、CAPTCHA、附件

## Risks / Trade-offs

- **Sliently drop 非 disabled email** → 攻擊者無法用此 endpoint 列舉帳號，但合法使用者誤 type email 不會收到提示 → 風險可接受（申訴量極低，admin 手動跟進）
- **無 admin UI MVP** → admin 必須讀 email digest + 開 DB query 處理 → 短期可接受（量小），量大時開後續 change
- **`appeal_enabled` 旗標** → 多一層耦合（前後端要同步） → 換來日後可一鍵關申訴 endpoint 的彈性

## Migration Plan

1. Alembic migration 建表（向前相容、無 backfill 需求）
2. 後端 endpoint + worker 部署
3. 前端 Lock card disabled 狀態部署
4. 全程不破壞既有 403 行為（response body 新增 field 為向前相容）
5. Rollback：alembic downgrade + 前端 revert；endpoint 移除即可
