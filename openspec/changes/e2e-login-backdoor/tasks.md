## 1. Config 與 Schema

- [x] 1.1 在 `backend/app/config.py` 的 `Settings` 加 `E2E_LOGIN_TOKEN: Optional[str] = None`
- [x] 1.2 在 `Settings` 加 pydantic validator：若 `E2E_LOGIN_TOKEN` 非 None 但長度 < 32 → raise `ValueError("E2E_LOGIN_TOKEN must be at least 32 chars")`
- [x] 1.3 跑 `pytest backend/tests/test_config.py -k e2e` 驗證 validator（含 None / 短 token / 合法 token 三 case）

## 2. Session TTL override（design decision: 15-min TTL override at session creation）

- [x] 2.1 在 `backend/app/core/sessions.py` 的 `create_session(...)` 簽名加 `ttl_override: Optional[timedelta] = None` 參數
- [x] 2.2 函數內部：`expires_at = now + (ttl_override or timedelta(days=settings.SESSION_TTL_DAYS))`
- [x] 2.3 加 pytest：預設呼叫（無 override）TTL 仍是 `SESSION_TTL_DAYS` × 1 day；帶 `ttl_override=timedelta(minutes=15)` 則 expires_at 距 now 為 15 min ± 1 sec

## 3. Rate limiter（design decision: in-memory IP rate limit, fail-only counter）

- [x] 3.0 實作 spec requirement「E2E login per-IP failure rate limit」（涵蓋 3.1–3.4 全部子任務）
- [x] 3.1 在 `backend/app/api/auth_e2e.py` 新建 module-level `_failure_log: dict[str, list[float]] = {}`
- [x] 3.2 寫 `_check_rate_limit(ip: str) -> bool` helper：清掉 60 秒前的 timestamp，若剩餘 > 5 回 False
- [x] 3.3 寫 `_record_failure(ip: str)` helper：append `time.monotonic()`
- [x] 3.4 加 pytest：5 次失敗後第 6 次回 False；60 秒（用 monkey-patched time）後 reset

## 4. Endpoint 實作（含 design decision: HMAC compare_digest over plain `==` 與 design decision: audit log via existing logger, structured fields）

- [x] 4.0 實作 spec requirement「E2E login backdoor endpoint (env-gated, audit-logged)」（涵蓋 4.1–4.8 全部子任務 + section 5 router 條件註冊）
- [x] 4.1 在 `backend/app/api/auth_e2e.py` 寫 `router = APIRouter(prefix="/auth", tags=["auth-e2e"])`
- [x] 4.2 實作 `GET /_e2e_login` handler：取 `token` query param、取 client IP（`request.client.host`，若有 `X-Forwarded-For` 則取第一個）、user-agent
- [x] 4.3 先檢查 rate limit：超限 → log `event=e2e_login_rate_limited` + 回 429
- [x] 4.4 用 `hmac.compare_digest(token.encode(), settings.E2E_LOGIN_TOKEN.encode())` 比對；不符 → `_record_failure(ip)` + log `success=false` + 回 401
- [x] 4.5 token 正確：查 user where `email == settings.ADMIN_EMAILS[0]`（user 不存在 → log error + 500，提示需先用 SSO 登入過一次建立 user record）
- [x] 4.6 呼叫 `create_session(user, ttl_override=timedelta(minutes=15))` 拿 session_id，set cookie（重用既有 SSO cookie 設定 — name / domain / Secure / HttpOnly / SameSite 全相同）
- [x] 4.7 log `event=e2e_login_attempt, success=true, ip, user_agent, user_email`
- [x] 4.8 回 302 redirect 到 `/`（讓 Claude MCP 自然進站）

## 5. 條件註冊 router（design decision: env-gated by route registration, not by runtime check）

- [x] 5.1 在 `backend/app/main.py` create_app 流程加：`if settings.E2E_LOGIN_TOKEN: app.include_router(auth_e2e.router)`
- [x] 5.2 寫 pytest（在 `test_auth_e2e.py`）：用 `monkeypatch.setenv("E2E_LOGIN_TOKEN", "")` 重建 app → `client.get("/auth/_e2e_login?token=x")` 回 404
- [x] 5.3 寫 pytest：設合法 token 重建 app → 同樣 path 帶錯 token 回 401（證明 route 有註冊）

## 6. 完整 endpoint pytest

- [x] 6.1 在 `backend/tests/test_auth_e2e.py` 寫 fixture：set 32+ 字元 token 到 env、預先 seed `ADMIN_EMAILS[0]` user 到 DB
- [x] 6.2 test：valid token → 302 + cookie + DB session row exists + expires_at ≈ now + 15 min
- [x] 6.3 test：invalid token → 401 + 無 cookie + audit log 含 `success=false`
- [x] 6.4 test：缺 token query param → 401
- [x] 6.5 test：5 次失敗後第 6 次 → 429 + 沒進到 token 比對（用 mock 確認 compare_digest 沒被呼叫）
- [x] 6.6 test：成功呼叫 10 次都不會被 rate limit
- [x] 6.7 跑 `pytest backend/tests/test_auth_e2e.py -v` 全綠

## 7. 部署驗證

- [ ] 7.1 push 到 main → Zeabur 自動 build；先**不設** `E2E_LOGIN_TOKEN` 部署一次
- [ ] 7.2 `curl -i https://podcastrag-api.zeabur.app/auth/_e2e_login?token=anything` 確認回 404
- [ ] 7.3 用 zeabur-variables skill 在 backend / worker / dispatcher / beat 4 個 service 設 `E2E_LOGIN_TOKEN=<openssl rand -hex 32 產生的 64 字元>`
- [ ] 7.4 等 redeploy 完成（Zeabur 介面看 deployment status）
- [ ] 7.5 `curl -i ".../auth/_e2e_login"` 不帶 token → 401
- [ ] 7.6 `curl -i ".../auth/_e2e_login?token=<正確>"` → 302 + Set-Cookie；用 cookie call `/admin/users` 確認 admin 權限拿得到
- [ ] 7.7 連續 6 次錯誤 token → 第 6 次回 429
- [ ] 7.8 把 token 寫入 `~/.config/podcastrag/e2e-token`，`chmod 600`

## 8. 文件 / 記憶更新

- [x] 8.1 更新 `src/releaseLog.jsx` 新增 v0.8 entry（雙語：標題 / 摘要）
- [x] 8.2 更新記憶 `feedback_browser_verification.md`：MCP 驗證流程改用 e2e-login，描述步驟（讀 token file → call endpoint → 拿 cookie → 進站）；舊 storage state fallback 留著但改為次選
- [x] 8.3 更新記憶 `reference_prod_storage_state.md`：標註新增 e2e-token 檔案、路徑、權限、輪換建議週期 90 天
