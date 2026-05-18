## Why

被停權使用者（auth callback 拒絕後）目前看到 Lock card 沒有任何申訴管道。`backend/app/api/auth.py` 雖然會 raise 403 `ACCOUNT_DISABLED`，但前端只能顯示「被停權」訊息然後死路一條，使用者只能透過 email/IM 私下找管理員陳情。為了讓誤判停權的使用者有正式申訴流程、也讓管理員有集中收件入口，需要在 Lock card disabled 狀態加申訴表單與後端 endpoint。

## What Changes

- Auth callback 收到 `ACCOUNT_DISABLED` 時，前端顯示 Lock card 第三狀態（disabled）含「提出申訴」按鈕
- 新增申訴 Modal：textarea（事由）+ 自動帶入 Google email + 送出按鈕
- 新後端 endpoint `POST /auth/appeal`：接受 `{ email, reason }`、寫進新 `account_appeals` 表
- Admin 通知：沿用既有 `app/workers/quota_digest.py` 模式，每日 digest 把當天新申訴 email 給 `ADMIN_EMAILS`
- MVP 範圍：**不開後台 admin UI**，管理員透過 email digest + DB 直查處理；UI 後續另開 change
- 不依賴外部服務（無第三方 ticketing）

## Non-Goals (optional)

- Admin 後台審核 UI（後續 follow-up change，需要時再開）
- 申訴後狀態回查 / 通知申訴人結果（MVP 走 email 人工回覆）
- 多次申訴 rate limit 以外的反濫用機制（CAPTCHA / 黑名單 IP 等）
- 申訴內容附件上傳

## Capabilities

### New Capabilities

- `account-appeal`: 被停權帳號的申訴受理流程，含 `POST /auth/appeal` endpoint、`account_appeals` 表、digest 通知 admin

### Modified Capabilities

- `auth-system`: 403 `ACCOUNT_DISABLED` response 加 `appeal_enabled: true` 旗標，引導前端顯示申訴入口
- `landing-page`: Lock card 加第三狀態 disabled（🚫 icon + 申訴 CTA）

## Impact

- Affected specs: `account-appeal`（新）、`auth-system`、`landing-page`
- Affected code:
  - New:
    - `backend/app/api/appeal.py`（FastAPI router）
    - `backend/app/models/account_appeal.py`
    - `backend/alembic/versions/xxxx_add_account_appeals.py`
    - `backend/tests/api/test_appeal.py`
    - `src/AppealModal.jsx`
  - Modified:
    - `backend/app/api/auth.py`（403 response 加 `appeal_enabled`）
    - `backend/app/workers/quota_digest.py`（或新建 sibling digest task）
    - `backend/app/main.py`（router 註冊）
    - `src/Shared.jsx`（Lock card 加 disabled 狀態 + 申訴按鈕）
    - `src/App.jsx`（auth callback 失敗判斷分流）
  - Removed: 無
- 無外部相依
- DB schema 新增單表（4-5 欄）、需 alembic migration
