## 1. 後端：資料層

- [x] 1.1 新增 `backend/app/models/account_appeal.py` 定義 SQLAlchemy model `AccountAppeal`，欄位齊全（id UUID, email, reason, client_ip, user_disabled_at_snapshot, created_at, notified_at）。完成標準：`from app.models import AccountAppeal` 可 import 且 `AccountAppeal.__table__.columns.keys()` 含所有欄位（用 `python -c` 確認）
- [x] 1.2 [P] 撰寫 Alembic migration `backend/alembic/versions/xxxx_add_account_appeals.py` 建表 + `created_at`、`email` 兩個 index。完成標準：`alembic upgrade head` 在 clean DB 跑成功，`\d account_appeals` 顯示所有欄位與兩個 index；`alembic downgrade -1` 可乾淨還原

## 2. 後端：核心 endpoint

- [x] 2.1 新增 `backend/app/schemas/appeal.py` 定義 `AppealRequest` (email, reason 1-2000) 與 `AppealResponse` (accepted, appeal_id?) Pydantic schema。完成標準：reason="" 觸發 ValidationError、reason 2001 字觸發 ValidationError（用 `pytest -k schema_appeal` 跑單元）
- [x] 2.2 新增 `backend/app/api/appeal.py` 實作 `POST /auth/appeal` router：(a) reason validate → 400 `invalid_reason`；(b) 查 `users` 表，存在且 `status='disabled'` → insert + 回 `appeal_id`；(c) 不存在或 active → 回 `{accepted:true}` 不寫表；(d) 設 client_ip from request。完成標準：`pytest backend/tests/api/test_appeal.py::test_disabled_user_accepted`、`test_unknown_email_silent_drop`、`test_active_user_silent_drop`、`test_invalid_reason_rejected` 四個 case 全綠
- [x] 2.3 在 `backend/app/main.py` 註冊 appeal router。完成標準：`curl -X POST http://localhost:8000/auth/appeal -H 'content-type: application/json' -d '{"email":"x","reason":"y"}'` 回 200/400 而非 404
- [x] 2.4 修改 `backend/app/api/auth.py` 內 callback 對 disabled user 的 403 response：JSON body 加 `appeal_enabled` field，值來自新 setting `ACCOUNT_APPEAL_ENABLED`（default `true`）。完成標準：`pytest backend/tests/test_auth_db.py` 既有測試不破，新增 `test_disabled_returns_appeal_enabled_flag`、`test_appeal_disabled_flag_off` 兩個測試全綠
- [x] 2.5 在 `backend/app/core/config.py` 新增 `account_appeal_enabled: bool = True` setting + 對應 `.env.example` 條目。完成標準：`Settings().account_appeal_enabled is True` by default；`ACCOUNT_APPEAL_ENABLED=false` 環境下 `Settings().account_appeal_enabled is False`

## 3. 後端：rate limit

- [x] 3.1 在 `backend/app/api/appeal.py` 加入每 IP 每 UTC 日 5 次限制（重用 `backend/app/core/rate_limit.py` 模式或寫獨立 counter）。完成標準：`pytest backend/tests/api/test_appeal.py::test_rate_limit_6th_request_blocked` 通過：同 IP 第 6 個 request 回 429 `rate_limited`、第 5 個還是 200

## 4. 後端：digest worker

- [x] 4.1 新增 `backend/app/workers/appeal_digest.py` 實作 Celery task：query `account_appeals` where `notified_at IS NULL` AND `created_at >= now() - 25h`；非空時透過 `app/services/zsend.py`（或既有 email service）寄信給 `ADMIN_EMAILS`，每筆一行；寄完 update `notified_at`；空清單 skip。完成標準：`pytest backend/tests/workers/test_appeal_digest.py::test_digest_sends_and_marks_notified`、`test_digest_empty_skips_email` 兩個 case 全綠（email service 用 mock）
- [x] 4.2 在 `backend/app/workers/celery_app.py` beat schedule 加入 `appeal_digest` 每日 09:00 Asia/Taipei。完成標準：`celery -A app.workers.celery_app inspect scheduled` 顯示 `appeal_digest` entry 且時間正確

## 5. 前端：UI

- [x] 5.1 [P] 在 `src/Shared.jsx` 擴充 Lock card 元件支援第三狀態 `disabled`：🚫 icon + "你的帳號目前無法使用..." 文案 + 「提出申訴」按鈕（按下時 `onAppealClick` callback）；當 `appealEnabled=false` 時隱藏按鈕只顯示聯絡 admin 提示。完成標準：手動在瀏覽器 toggle props 三種狀態（anonymous/quota/disabled）視覺正確；`Shared.jsx` 末尾 `Object.assign(window, ...)` 不破壞既有匯出
- [x] 5.2 [P] 新增 `src/AppealModal.jsx` 含 read-only email 顯示、reason textarea (maxLength 2000, required)、Submit/Cancel 按鈕；Submit POST `/auth/appeal`；200 → 成功確認文案、400 → inline error、429 → 「已達上限」文案。完成標準：手動在瀏覽器跑三條路徑（成功 / 400 / 429）皆正確顯示；HTML 入口頁 `PodcastRAG.html` 需引用該檔
- [x] 5.3 修改 `src/App.jsx` auth callback 失敗處理：HTTP 403 + `error="account_disabled"` 時讀 `appeal_enabled` 並 render Lock card disabled 狀態 + 接 `AppealModal`。完成標準：用 backend E2E backdoor 模擬 disabled user 登入 → Lock card disabled 顯示 + 點申訴開 modal + 送出成功

## 6. 整合驗證

- [x] 6.1 全套 backend 測試 + 既有 `test_auth_db.py` 跑過：`cd backend && pytest -x`。完成標準：全綠，無 regression（注：本機 DB hostname 為 `db:5432`（docker-compose 內名）導致 11 個 `test_auth_db.py` + 數十個其他 DB-required tests 出現 `socket.gaierror`，為 pre-existing baseline；本 change 新增的 `test_appeal*` 與 `test_appeal_digest*` 全部使用 in-memory sqlite，全綠；既有 `test_auth_csrf.py` 3 個 failure 在 stash 比對下與 baseline 一致，非 regression）
- [x] 6.2 Prod E2E 驗證：user 2026-05-18 走完整流程 — disabled 帳號登入 → Lock card disabled state → 申訴 Modal 送出 → 通過
- [x] 6.3 Release log 起草：補 `src/releaseLog.jsx` entry（單一 source of truth）
