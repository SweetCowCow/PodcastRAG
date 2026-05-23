## Why

Admin 帳號（per `Settings.admin_email_set` 白名單 + `UserService` 建帳號時設 `role=admin`）跑 chat / query 跟一般 user 一樣每天扣 `quota_remaining`（default 30 / day）。連帶後果：

- **眼前**：跑 token-truncate eval gate（34 record × 平均 3 turn ≈ 102 chat 請求）開頭 ~30 個 request 燒光 admin 帳號的 daily quota，後續全 HTTP 429 `quota_exhausted`，2026-05-23 的整輪 eval `answer_match` 跌到 0.025（垃圾值），完全沒驗到 `agent-token-budget-and-tool-truncate` 的真實 fix 效果。
- **未來**：admin dogfood、chrome-devtools-mcp prod smoke、release 前 manual QA 全會反覆撞 429 — 每次都要 admin 手動 top-up 才能繼續。
- 影響 eval pipeline 整條：本 fix merge 前無法重跑 token-truncate eval 也無法跑後續任何 agentic-prompt-grounding-and-ordinal-tool 等 follow-up change 的驗證。

## Why now

`landing-redesign-hotfix-transcript-and-audio` 剛 archive（2026-05-23）— pending propose queue 排序第 1 順位就是本 change（per `project_session_resume_2026_05_24_morning.md`）。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `user-quota`: 「Query endpoint atomically decrements quota」requirement 加例外：role=admin 的 authenticated user SHALL NOT 觸發 quota decrement，SHALL NOT 收到 429 `quota_exhausted`。非 admin 行為完全不變。

## Problem

對 admin 帳號跑 chat eval / dogfood / prod smoke：
- 開頭幾個 request 正常回應，`quota_remaining` 從 30 → 0 依序遞減
- 第 31 個 request 起 backend 回 `HTTP 429 {error_code: "quota_exhausted"}`
- Admin 必須手動呼叫 top-up endpoint 補 quota 才能繼續
- 任何超過 30 個 chat 請求的批次作業（eval、bake-off、自動化 smoke）對 admin 等同被 rate-limit 卡死

## Root Cause

`_atomic_decrement_quota`（backend/app/api/query.py 內的 helper）對所有 authenticated user 一視同仁執行 UPDATE — 沒檢查 `user.role`。 `authentication-system` change 雖然引入了 admin role（per `UserService.create_user_from_oauth` 內依 `admin_email_set` 設 `role`），但 quota path 完全沒用到這個 role 欄位。

設計時的隱含假設是「admin 平常不會自己跑 query」— 這個假設在加了 eval / dogfood / E2E backdoor 流程後不成立。

## Proposed Solution

在 query endpoint 的 quota path 加 admin short-circuit：

1. **位置**：query.py 的 chat endpoint（呼叫 `_atomic_decrement_quota` 之前）— 不動 helper 本身。
2. **條件**：`if user.role != "admin"` 才呼叫 `_atomic_decrement_quota`。
3. **回應 `quota_remaining` 欄位**：
   - 非 admin：仍回 `_atomic_decrement_quota` 的真實 remaining（行為不變）
   - admin：回特殊 sentinel 值表示 unlimited — 用 `-1`（schema 內既有的 int 欄位，用負數區隔；前端可選擇顯示 ∞ 或不顯示，前端調整不在本 change scope）
4. **`total_queries` 計數**：admin 仍 +1，方便事後統計 admin 用量；用單獨小 UPDATE（不走 `_atomic_decrement_quota`）。

## Non-Goals

- **不**動 `_atomic_decrement_quota` helper 本身 — 保持單一職責（給非 admin 用）。
- **不**動 `quota_remaining` 欄位定義 / DB schema — 不加新欄位、不加 `is_unlimited` flag。
- **不**動前端顯示 — quota meter / lock card / quota request flow 全部不變；前端見到 `quota_remaining=-1` 就照 -1 顯示也 OK（admin 本來就不太看自己 quota），如要美化前端另開 change。
- **不**修 anonymous IP rate limit 路徑（admin 是 authenticated user，不會走 IP limit 分支）。
- **不**修 events / public search endpoint（per spec 本來就不扣 quota）。
- **不**動 chat agentic vs rule-based 兩條路徑的選擇 — 兩條路徑都走同一個 query endpoint，bypass 對兩者皆生效。
- **不**動 admin 的 top-up endpoint（既有 `admin can adjust quota_remaining` requirement 保留 — 給其他 user 用）。

## Success Criteria

- **A1**：Admin 帳號 (`role=="admin"`) 連續跑 200 個 chat request：全部 HTTP 200，`quota_remaining` 在 response 中為 `-1`，DB 內 `users.quota_remaining` **完全不變**（保留建帳號時設的 default 30）。
- **A2**：Admin 跑同樣 200 個 request：DB `users.total_queries` 從 N 增加到 N+200（仍計數，方便事後統計）。
- **A3**：非 admin user (`role=="member"`) 行為 zero regression：原本 `quota_remaining=10` 跑 10 個 request 後 `quota_remaining=0`，第 11 個回 429 — 跟改前一致。
- **A4**：spec scenario「Concurrent chat queries do not over-spend quota」對非 admin user 仍 pass — admin bypass path 不引入新的 race condition。
- **A5**：本機 pytest（新增 fixture：admin user + 100 個連續 request，驗 quota_remaining 不變）全綠。
- **A6**：merge + redeploy backend 後重跑 `backend/scripts/run_chat_agent_eval.py --label token-truncate-rerun-post-bypass`，全 34 record 拿到非 429 結果，`answer_match` 回到 baseline 範圍（≥ 0.5）— 此為附加驗證，不阻塞 archive。

## Impact

- Affected code:
  - Modified:
    - backend/app/api/query.py
  - New:
    - backend/tests/test_admin_quota_bypass.py
  - Removed:
    - (none)
- Affected specs: user-quota
