## Why

Claude 在做 UI 驗證時（chrome-devtools-mcp / playwright）需要 admin session，目前只能靠 `~/.config/podcastrag/playwright-state.json` 預存的 cookie，14 天就過期，且 Google SSO 互動式登入無法在無頭流程中跑。需要一條受控、env-gated 的後門，讓自動化驗證能在 prod / staging 取得 admin session 而不犧牲安全性。

## What Changes

- 後端新增 `GET /auth/_e2e_login?token=<TOKEN>` 端點：驗 token、查 `ADMIN_EMAILS[0]` 對應 user、發 session cookie（重用現有 session 機制）
- 預設**完全停用**：只有當 `E2E_LOGIN_TOKEN` env var 非空時才註冊 route；env 缺漏時連 404 都不回（route 不存在）
- Token 用 HMAC 比對（`hmac.compare_digest`）防 timing attack；最小長度 32 字元
- Session TTL 強制 15 分鐘（不論 env 設多長），避免後門 session 變長期憑證
- 每次成功/失敗呼叫寫 audit log（既有 logger）：timestamp / IP / user-agent / 成功與否；失敗回 401 + log warning
- IP rate limit：同一 IP 每分鐘 > 5 次失敗 → 60 秒內 reject（in-memory，重啟即清）
- 完成後手動操作（**不在這個 change 範圍內，但寫到 deployment notes**）：
  - Zeabur env `E2E_LOGIN_TOKEN` 設一個 64 字元隨機 token（4 個 service 都要：backend / worker / dispatcher / beat — 雖然只有 backend 用到，但保持一致）
  - 同一 token 寫入 `~/.config/podcastrag/e2e-token`（mode 600）給 Claude MCP 流程讀
  - 更新 `feedback_browser_verification.md` 記憶：Claude MCP 驗證流程改用 e2e-login，不再依賴 14 天 storage state

## Non-Goals

- 不做 UI 入口（沒有按鈕、沒有 admin 設定面板讓人手動觸發）— 純 API、純 env-gated
- 不發給多個 admin、不接受指定 email 參數 — 永遠只發給 `ADMIN_EMAILS[0]`
- 不持久化 audit log 到 DB — 走既有 logger 即可（避免新 schema migration）
- 不做 Redis-based rate limit — in-memory 夠用，後門流量極低

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `auth-system`: 新增 e2e login backdoor requirement（env-gated、TTL 15 min、HMAC token、audit log、IP rate limit）

## Impact

- Affected specs: `auth-system`（modified — 新增 e2e-login backdoor requirement）
- Affected code:
  - New: `backend/app/api/auth_e2e.py`（router）
  - New: `backend/tests/test_auth_e2e.py`（pytest 覆蓋 token 驗證 / TTL / rate limit / disabled-by-default）
  - Modified: `backend/app/main.py`（條件註冊 router）
  - Modified: `backend/app/config.py`（新增 `E2E_LOGIN_TOKEN: Optional[str] = None`）
  - Modified: `backend/app/core/sessions.py`（或 session 建立處 — 接受 override TTL 參數）
  - Modified: `src/releaseLog.jsx`（v0.8 entry）
- Deployment（不算 code，但同 change 完成後要做）：
  - Zeabur 4 個 service 設 `E2E_LOGIN_TOKEN`（用 zeabur-variables skill）
  - Token 同步寫 `~/.config/podcastrag/e2e-token`（mode 600）
