## 0. Spec & Proposal 對應

- Spec requirement A：「Chat agent eval runner SHALL capture debug_trace into result JSON」→ task 1.x + 3.x
- Spec requirement B：「Chat agent eval runner SHALL read credentials from environment variables, not argv」→ task 2.x
- Proposal section (A) 接 debug_trace → task 1.x + 3.x
- Proposal section (B) auth-token 走 env → task 2.x
- Proposal section (C) 重跑 round 1 eval → task 4.x

## 1. 接 debug_trace gate

實作 spec requirement「Chat agent eval runner SHALL capture debug_trace into result JSON」

- [x] 1.1 Chat agent eval runner SHALL capture debug_trace into result JSON — `backend/scripts/run_chat_agent_eval.py` 的 `_query_chat` helper 把 query URL 從 `/shows/{show_id}/query` 改成 `/shows/{show_id}/query?debug_trace=true`
- [x] 1.2 `_query_chat` return value 從「只回 `answer` + `tool_calls`」改成同時 return `(answer, tool_calls_made, trace_blob)`，其中 `trace_blob` 含 `tool_calls`（每個含 `args` / `result_full`）+ `trace.llm_calls` + `trace.stage_timings`，若 response 沒這些欄位（degraded mode）回 `None` 並印 stderr warning
- [x] 1.3 turn 處理迴圈接住 `trace_blob`，寫進 result item 的新 `trace` 欄位；既有 `tool_calls_made` (tool name list) 維持不動以 backward compat
- [x] 1.4 stderr warning 訊息明寫「debug_trace 被靜默拒（session 可能不是 admin），continuing with degraded result」並指向 spec requirement 名

## 2. 換 auth-token + origin 走 env

實作 spec requirement「Chat agent eval runner SHALL read credentials from environment variables, not argv」

- [x] 2.1 Chat agent eval runner SHALL read credentials from environment variables, not argv — 移除 argparse 的 `--auth-token` 參數；read `os.environ.get("PODCASTRAG_SESSION", "")`；空 string exit 2 + stderr 印「PODCASTRAG_SESSION env var is required; export it from /tmp/podcastrag_session.txt before running」
- [x] 2.2 移除 argparse 的 `--origin` 參數；read `os.environ.get("PODCASTRAG_ORIGIN", "")`；空就走原本「derive from backend-url」邏輯
- [x] 2.3 docstring + 範例命令更新成 `PODCASTRAG_SESSION="$(cat /tmp/podcastrag_session.txt)" PODCASTRAG_ORIGIN=https://podcastrag.zeabur.app python backend/scripts/run_chat_agent_eval.py --dataset ... --backend-url ... --label ... --out ...`
- [x] 2.4 main() 啟動時先驗證 env，再印 `Running chat eval: <label>` banner（避免空 env 還跑半天才炸）

## 3. 驗證 trace capture 行為

實作 spec requirement「Chat agent eval runner SHALL capture debug_trace into result JSON」(承上)

- [x] 3.1 寫一支 `backend/tests/test_run_chat_agent_eval_trace.py`：mock `_post` 回 `{trace: {llm_calls:[...], stage_timings:{...}}, tool_calls:[{name, args, result_full, ...}]}`，跑一個 single-turn dataset，assert result JSON `turns[0].trace` 形狀正確、`turns[0].tool_calls_made` 沒消失
- [x] 3.2 同檔案加 degraded-mode test：mock `_post` 回 `{trace: null, tool_calls: null}`，assert result `turns[0].trace == null`、exit code 0、stderr 含 "debug_trace"
- [x] 3.3 同檔案加 env-missing test：unset `PODCASTRAG_SESSION` 跑 main，assert exit code != 0、stderr 含 "PODCASTRAG_SESSION"

## 4. 重跑 round 1 eval 拿真實 trace

實作 proposal section (C)

- [x] 4.1 確認 prod backend 跑的是 round 1 prompt（已 revert round 2、archive 已 ship；curl `/health` + grep deployment log SHA 確認）
- [x] 4.2 重新登入 E2E backdoor 抓 fresh `PODCASTRAG_SESSION`（之前 session 可能過期）；export 進 env
- [x] 4.3 跑 `PODCASTRAG_SESSION=... PODCASTRAG_ORIGIN=https://podcastrag.zeabur.app python backend/scripts/run_chat_agent_eval.py --dataset backend/eval/datasets/extended-multi-turn-40.json --backend-url https://podcastrag-api.zeabur.app --label v1-with-trace --out backend/eval/results/chat_eval_grounding_v1_with_trace.json`
- [x] 4.4 抽 5 個 round 1 severe case（b12 / b22 / b27 / b29 / mt01 t2）人工檢查 `turns[].trace.tool_calls`：args 正確、result_full 非空、能對 final answer 做 retrieved-vs-fabricated 比對

## 5. Spectra archive 前置

- [x] 5.1 跑 `backend/tests/test_run_chat_agent_eval_trace.py` 三 case 全綠
- [x] 5.2 跑現有 unit test `backend/tests/test_chat_agent_loop.py` 等 chat agent 既有 test 不受影響（本 change 沒動 backend）
- [x] 5.3 跑 `spectra validate eval-runner-debug-trace-capture` + `spectra analyze` 無 Critical / Warning
- [x] 5.4 案例 study 文件 `docs/case-studies/eval-runner-debug-trace-capture-2026-05-24.md` 補 5 severe case 真實 root cause（基於 trace），對比 v2 archive 時的 LLM-classifier 推測結果是否吻合
- [x] 5.5 跑 `/spectra-archive eval-runner-debug-trace-capture`
