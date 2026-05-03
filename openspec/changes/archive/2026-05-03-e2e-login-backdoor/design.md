## Context

PodcastRAG 已上線 Google SSO（auth-system spec）。Claude 在 chrome-devtools-mcp 流程中需要 admin session 才能驗證 `/admin/*` 與受 gate 的 `/query`。目前作法是預存 storage state（`~/.config/podcastrag/playwright-state.json`，14 天過期），且 Google SSO 互動式登入無法在無頭 / 非互動流程中完成 — 每 14 天就要使用者手動跑 `save-cookies.sh` 重抓，磨損驗證循環。

需要一條後門：API-only、env-gated、預設關閉、可在 prod / staging 用最小信任面取得 admin session。同類做法在內部測試系統常見（例如 Rails 的 test mode bypass、Django 的 `LOGIN_REQUIRED=False` 條件），但 prod 啟用必須有多層保護。

Stakeholders：
- 使用者（16249390+SweetCowCow@users.noreply.github.com）— 唯一受影響的 admin
- Claude（自動化驗證流程）— 主要 consumer
- 安全：本 change 不能讓未持 token 者拿到 admin

## Goals / Non-Goals

**Goals**
- 持有正確 token 的呼叫者能在 1 次 HTTP request 內拿到合法 admin session cookie
- 未設 `E2E_LOGIN_TOKEN` env 的部署完全沒有此 endpoint（route 不註冊，404 都不該出現此 path）
- token 驗證對 timing attack 安全
- 後門 session TTL 強制 ≤ 15 min，不論 `SESSION_TTL_DAYS` 設多長
- 失敗呼叫被觀察得到（audit log + IP rate limit）

**Non-Goals**
- 不發給任意 email — 永遠只發 `ADMIN_EMAILS[0]`
- 不做 UI / admin panel 入口
- 不做 DB-persisted audit log（既有 logger 已足）
- 不做分散式 rate limit — in-memory 即可（後門流量極低，重啟清空可接受）
- 不接受 token 從 query string 以外的位置傳入（避免 header / cookie / body 多入口增加攻擊面）

## Decisions

### Decision: env-gated by route registration, not by runtime check

**選擇**：在 `main.py` 啟動時讀 `E2E_LOGIN_TOKEN`，**只有 token 非空才註冊 router**。

**為什麼不用 runtime if-else**：runtime 檢查表示 path 永遠存在 — 即使 disabled 也回 401，會洩漏「這台 server 支援 e2e backdoor」資訊，給攻擊者偵察線索。Route-level gating 讓 disabled 部署完全不存在這個 path，回 404 跟其他亂試 URL 沒有區別。

**Alternatives considered**：feature flag in DB → 過重；middleware-level reject → 同樣會回 401。

### Decision: HMAC compare_digest over plain `==`

**選擇**：`hmac.compare_digest(provided_token, settings.E2E_LOGIN_TOKEN)`

**為什麼**：避免短路比對洩漏 token 前綴 timing 資訊。Python 內建、零依賴。Token 最小長度強制 32 字元（在 config validator 檢查），避免使用者設太短的 token。

### Decision: 15-min TTL override at session creation

**選擇**：在 `create_session(user, ttl_override=timedelta(minutes=15))` 時傳 override，後門 session 永遠 15 min。

**為什麼**：站台預設 `SESSION_TTL_DAYS=30`（auth-system spec）。後門即使被洩漏，最多 15 min 後失效，且不影響正常 SSO session。Override 機制要在 `core/sessions.py` 加參數，正常路徑不受影響（預設值仍是 30 天）。

**Alternatives considered**：用單獨的 e2e session table → 增加 schema 複雜度；發 short-lived JWT 不寫 DB → 跟現有 cookie session 機制不一致。

### Decision: in-memory IP rate limit, fail-only counter

**選擇**：`dict[str, list[float]]`（IP → timestamp list of last 5 failures），每分鐘 > 5 次失敗 → 60 秒內 reject 同 IP。**只計失敗**（成功不計），避免 Claude 連續驗證流程被自家 rate limit 擋到。

**為什麼**：後門的威脅模型是「攻擊者亂猜 token」，成功的呼叫者按定義是合法。In-memory 夠用因為流量極低（Claude 平均每個驗證 session 1-2 次呼叫）。重啟清空可接受 — 攻擊者就算抓到重啟時機，仍受 32 字元 HMAC token 保護。

**Alternatives considered**：Redis sliding window → 過重；slowapi → 多一個依賴。

### Decision: Audit log via existing logger, structured fields

**選擇**：`logger.info("e2e_login_attempt", extra={"ip": ..., "ua": ..., "success": bool, "user_email": ...})` — 走既有 structured logger，不新建 audit table。

**為什麼**：勾稽用既有 log aggregation（Zeabur log 介面）即可。新 DB table 表示要 migration、要 admin UI 看 log，與「最小變更」原則不符。

## Risks / Trade-offs

- **[Token 洩漏]** → Mitigation：token 只存 Zeabur env（不進 git）+ 本機 mode 600；TTL 15 min；可隨時改 env value 旋轉；audit log 可事後追查異常 IP
- **[In-memory rate limit 在 multi-worker 下不共享]** → Mitigation：backend service 預設 1 worker（uvicorn `--workers 1`，目前部署現況）；若未來擴 multi-worker，攻擊者最多 N×5 次/分鐘嘗試，仍遠不足以暴力 32 字元 token
- **[Route 註冊條件忘記跑 / 部署順序錯]** → Mitigation：tasks 包含 prod 驗證步驟（curl `/auth/_e2e_login` 不帶 token 應 401，不設 env 部署應 404）
- **[Override TTL 寫錯影響到正常 session]** → Mitigation：`create_session` 的 `ttl_override` 預設 None；新增 pytest 確保預設路徑 TTL 仍是 30 天

## Migration Plan

1. 寫 code + pytest，本機 `pytest backend/tests/test_auth_e2e.py` 全綠
2. 不設 `E2E_LOGIN_TOKEN` 部署一次 → 確認 prod `curl /auth/_e2e_login?token=x` 回 404
3. 設 `E2E_LOGIN_TOKEN=<隨機 64 字元>` 到 4 個 Zeabur service（backend / worker / dispatcher / beat），雖然只有 backend 用到但保持一致避免下次有人困惑
4. 部署後驗證：
   - `curl /auth/_e2e_login` 不帶 token → 401 + audit log
   - `curl /auth/_e2e_login?token=<正確>` → 302 + Set-Cookie + audit log
   - 連續 6 次錯誤 token → 第 6 次 429
5. 寫 token 到 `~/.config/podcastrag/e2e-token`（mode 600）
6. 跑一次 chrome-devtools-mcp e2e 流程證明 Claude 能用此流程拿 admin session

**Rollback**：把 `E2E_LOGIN_TOKEN` env 從 4 個 service 移除 → 重啟後 route 不註冊。Code 留著沒風險。

## Open Questions

- Token 旋轉週期？建議每 90 天手動換一次（寫進 `feedback_browser_verification.md`），但本 change 不做自動化
- 未來是否要加「臨時延長 TTL」參數（例如某些 e2e 流程跑超過 15 min）？暫時不做，等真的卡到再說
