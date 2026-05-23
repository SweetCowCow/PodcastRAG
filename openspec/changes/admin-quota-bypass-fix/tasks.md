## 1. Add admin bypass branch in query endpoint

- [x] 1.1 In `backend/app/api/query.py`, locate the call site of `_atomic_decrement_quota(db, user.id)` inside the chat endpoint handler (the function decorated with the `POST /shows/{show_id}/query` route).
- [x] 1.2 Replace the unconditional `quota_remaining = await _atomic_decrement_quota(db, user.id)` with a role check:
  - When `user.role == "admin"`: skip `_atomic_decrement_quota`; run a separate small UPDATE `users SET total_queries = total_queries + 1 WHERE id = :user_id` (commit), then set `quota_remaining = -1`.
  - When `user.role != "admin"` (i.e. `member`): keep the existing `quota_remaining = await _atomic_decrement_quota(db, user.id)` call unchanged.
- [x] 1.3 Implement the admin-side `total_queries` UPDATE as a small inline helper or inline SQL so `_atomic_decrement_quota` itself remains untouched (single-responsibility: that helper still only serves non-admin path and still raises 429 when row count is 0).
- [x] 1.4 Confirm `_atomic_decrement_quota` is NOT called for admin under any code path in this endpoint by searching the function body after the edit (`grep _atomic_decrement_quota` should show one call inside an `else` / non-admin branch only).
- [x] 1.5 Confirm the response builder downstream uses the new `quota_remaining` value verbatim (admin gets -1 in JSON payload). No additional schema change is needed — existing `quota_remaining: int` field carries `-1` as a sentinel.

## 2. Add pytest coverage for the new behavior

- [x] 2.1 Create `backend/tests/test_admin_quota_bypass.py` that imports the test client fixture used by existing admin tests (see `backend/tests/test_admin_api_keys.py` for the pattern — same async client + auth helpers).
- [x] 2.2 Add test `test_admin_quota_not_decremented_after_n_requests`: build an admin user with `quota_remaining=30, total_queries=0`, send 100 sequential chat requests (mock downstream LLM + embedding to avoid real API calls), assert all 100 responses are HTTP 200 with `quota_remaining=-1` in body, then read back the DB row and assert `quota_remaining=30` and `total_queries=100`.
- [x] 2.3 Add test `test_admin_bypass_when_quota_zero`: build an admin user with `quota_remaining=0`, send one chat request, assert HTTP 200 + `quota_remaining=-1` (no 429) + DB row still `quota_remaining=0`.
- [x] 2.4 Add test `test_member_quota_still_decrements`: build a `role="member"` user with `quota_remaining=2`, send 3 chat requests, assert request 1 + 2 return HTTP 200 with `quota_remaining=1` then `0`, request 3 returns HTTP 429 `quota_exhausted`, DB row reads `quota_remaining=0, total_queries=2`.
- [x] 2.5 Add test `test_member_concurrent_does_not_overspend`: build a `role="member"` user with `quota_remaining=1`, dispatch 2 concurrent chat requests via `asyncio.gather`, assert exactly one succeeds and one returns 429 (regression test for the existing concurrent scenario in spec).
- [x] 2.6 Run `cd backend && pytest tests/test_admin_quota_bypass.py -v` locally and confirm all 4 tests pass with exit code 0.

## 3. Ship to prod + re-run eval gate

- [x] 3.1 Commit + push to main (gitleaks scan first per `feedback_public_repo_commit_safety.md`).
- [x] 3.2 Trigger backend redeploy: `npx -y zeabur service redeploy --id 69eb10360da29f05f49a4b0b -y --interactive=false` (backend service id per `project_pending_changes.md`).
- [x] 3.3 Wait for RUNNING; verify by curl `https://podcastrag-api.zeabur.app/me` returns 200 with admin role.
- [x] 3.4 Quick prod smoke (admin path): refresh E2E backdoor session (per `reference_e2e_backdoor.md`), send 35 sequential chat requests to `https://podcastrag-api.zeabur.app/shows/{any_show_id}/query` mode=chat with a trivial prompt; assert all 35 return HTTP 200 (not 429) and last response body has `quota_remaining=-1`.
- [x] 3.5 Re-run `backend/scripts/run_chat_agent_eval.py --dataset backend/eval/datasets/extended-multi-turn-40.json --label token-truncate-rerun-post-bypass-2026-05-23 --backend-url https://podcastrag-api.zeabur.app --auth-token <SESSION> --top-k 5 --origin https://app.podcastrag.app --out backend/eval/results/chat_eval_token_truncate_rerun_post_bypass.json`. Launch via nohup + persistent log per `feedback_background_task_lifecycle.md`.
- [x] 3.6 After eval finishes, confirm `answer_match` is back in baseline range (≥ 0.5 — previous baseline before token-truncate change was 0.55 from `multi-turn-40-add-recall-ground-truth` archive). Also confirm `agent_truncated` field 在 b20 那題沒出現（這是 token-truncate fix 的真正驗證）。
- [ ] 3.7 Append result summary to `docs/case-studies/landing-redesign-hotfix-2026-05-24.md` under a "Follow-up: admin-quota-bypass-fix + token-truncate eval rerun" section (file is not git-tracked per `feedback_case_studies_no_commit.md`).

## 4. Release log + archive

- [ ] 4.1 Draft release log entry for `src/releaseLog.jsx`：tag=fix, milestone=v1.8, title「Admin 帳號跑 eval 不再被自己擋」(zh) /「Admin Accounts No Longer Block Themselves on Quota」(en), 3-4 bullet 講「admin 不扣 quota / total_queries 仍計數 / 一般使用者 quota 行為不變 / 為什麼這個 fix 重要（解開 eval pipeline）」. Wait for user confirmation before committing.
- [ ] 4.2 Bump `index.html` cache-bust for `src/releaseLog.jsx` (current `?v=6` → `?v=7`).
- [ ] 4.3 Run `/spectra-archive admin-quota-bypass-fix` only after task 3.6 evidence is captured AND user approves release log draft.
