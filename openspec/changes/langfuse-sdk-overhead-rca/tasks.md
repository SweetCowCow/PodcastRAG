# Tasks — langfuse-sdk-overhead-rca

## Phase 1: Instrumentation code

- [x] 1.1 修 `backend/app/core/config.py` Settings — 加 `EVAL_TRACING_TIMING_PROBE: bool = False` field（per `feedback_pydantic_settings_extra_forbid_leaks.md` 確認 Settings 已有 `extra="ignore"`）
- [x] 1.2 修 `backend/eval/tracing/langfuse_setup.py` — module-level 讀 `settings.EVAL_TRACING_TIMING_PROBE` 一次到 `_TIMING_PROBE_ENABLED` 常數（避免 per-call env read）
- [x] 1.3 修 `backend/eval/tracing/langfuse_setup.py::trace_span` — 加 `_timed_call(name, fn, *args, **kwargs)` helper（no-op 當 `_TIMING_PROBE_ENABLED=False`、用 `time.perf_counter()` + `logger.info("langfuse_timing: span_name=%s op=%s elapsed_ms=%.3f", ...)` 當 True）
- [x] 1.4 修 `trace_span` 內四個 suspect operation 套上 `_timed_call`：
  - `enter`：`with langfuse.start_as_current_observation(...) as obs:` 進入點
  - `exit`：`with` block 退出點（用 try/finally + elapsed 自己量）
  - `update`：`obs.update(**cloud_payload)` call
  - `get_trace_id`：`langfuse.get_current_trace_id()` call
- [x] 1.5 修 `trace_span` 加 per-span summary log：四個 op 都做完後 emit `logger.info("langfuse_timing_summary: span_name=%s total_ms=%.3f enter=%.3f exit=%.3f update=%.3f get_trace_id=%.3f", ...)`（no-op 當 flag False）

## Phase 2: Tests

- [x] 2.1 新增 `backend/tests/eval/tracing/test_timing_probe.py` 含 3 個 unit test：
  - `test_probe_disabled_no_log_emission` — patch `_TIMING_PROBE_ENABLED=False`、呼叫 `_timed_call(name, lambda: None)`、確認 caplog 沒抓到 `langfuse_timing` 開頭 lines
  - `test_probe_enabled_emits_per_op_log` — patch `_TIMING_PROBE_ENABLED=True`、呼叫 `_timed_call("test_op", lambda: time.sleep(0.001))`、caplog 含一行 `langfuse_timing: op=test_op elapsed_ms=` 且 elapsed_ms ≥ 1.0
  - `test_probe_disabled_zero_overhead` — patch False、1000 次 `_timed_call` 總 elapsed < 10ms（per-call < 0.01ms）
- [x] 2.2 local 跑 `pytest backend/tests/eval/tracing/test_timing_probe.py -v` 確認綠

## Phase 3: Prod deploy + Phase 2 量測

- [ ] 3.1 commit + push main 觸發 backend redeploy；gitleaks staged 0 finding；commit msg 不洩 secret per `feedback_public_repo_commit_safety.md`
- [ ] 3.2 等 backend RUNNING per `feedback_zeabur_deploy_monitor_pattern.md`
- [ ] 3.3 toggle `EVAL_TRACING_ENABLED=true` + `EVAL_TRACING_TIMING_PROBE=true` × 4 service (backend / worker / dispatcher / beat) + redeploy backend；走 `feedback_zeabur_variable_create_dumps_env.md` redirect stdout
- [ ] 3.4 等 backend RUNNING
- [ ] 3.5 修 `/tmp/latency_probe.py` 把 REPS_PER_QUERY 從 18 改成 7（28 main + 5 warmup = 33/phase）
- [ ] 3.6 跑 OFF phase：`python3 /tmp/latency_probe.py off /tmp/latency_rca_off.json`（OFF phase 需要 `EVAL_TRACING_ENABLED=false`、所以先 toggle 回 false redeploy 再跑、然後再 toggle 回 true redeploy 跑 ON）
  - 替代簡化路徑：跳過 OFF phase 重量測（已有 4.4 OFF baseline 在 /tmp/latency_off.json 可直接 reuse、commit hash 雖不同但 retrieve 路徑沒變）。建議走這條省一輪 redeploy
- [ ] 3.7 跑 ON phase：`python3 /tmp/latency_probe.py on /tmp/latency_rca_on.json`（env=true 狀態下）
- [ ] 3.8 下載 prod runtime log：`npx zeabur deployment log --deployment-id <latest> --type runtime -i=false > /tmp/prod_runtime.log 2>&1`、立刻 sed redact `?token=` `?key=` `?secret=` 等敏感參數 per `feedback_zeabur_deployment_log_leaks_query_string.md`
- [ ] 3.9 寫 aggregation script `/tmp/timing_aggregate.py`：parse `/tmp/prod_runtime.log` 的 `langfuse_timing:` + `langfuse_timing_summary:` lines、group by span name、算 per-op P50/P95 + per-query (b06/b11/b18/b20) breakdown、印 markdown table
- [ ] 3.10 跑 aggregation、產出 `/tmp/timing_breakdown.md`、確認哪個 op (enter/exit/update/get_trace_id) 是 dominant contributor

## Phase 4: Decision + cleanup

- [ ] 4.1 toggle `EVAL_TRACING_ENABLED=false` + `EVAL_TRACING_TIMING_PROBE=false` × 4 service + redeploy backend
- [ ] 4.2 等 backend RUNNING、curl `/query` smoke 驗 tracing 關了
- [ ] 4.3 寫 `docs/case-studies/langfuse-sdk-overhead-rca-2026-05-XX.md`：
  - (a) Background 連回 4.4 + parked span-writer-batch-queue
  - (b) Phase 1-3 全程紀錄
  - (c) Per-op timing breakdown table（從 /tmp/timing_breakdown.md 抄）
  - (d) Identified bottleneck（依結果寫）
  - (e) Forward path 選定（3a payload-trim / 3b instrumentation-pattern / 3c self-host）+ rationale
  - (f) Follow-up change 名字 + 起手 SOP
- [ ] 4.4 依 Phase 3 結論更新 memory：
  - `project_pending_change_candidates.md` 依結論調整 `langfuse-self-host-evaluation` 優先級
  - `project_langfuse_cloud_free_track_usage.md` 補真實 SDK overhead 數字 + 哪個 op 是 bottleneck
  - `feedback_no_guessed_numbers_from_memory.md` 紀律案例：本次 RCA 兩輪 wrong hypothesis 教訓
- [ ] 4.5 更新 `docs/roadmap.md` archive 表加 langfuse-sdk-overhead-rca entry + 衍生待 propose 段加選定的 forward change
- [ ] 4.6 release log entry `src/releaseLog.jsx`：tag `experiment`、雙語使用者視角講「為了搞清楚為什麼 trace 觀察會慢，做了一輪量測 spike、找到真正瓶頸是 X、下一步開 Y change 修」

## Phase 5: Commit hygiene + archive

- [ ] 5.1 每階段 commit 前跑 `gitleaks protect --staged --no-banner --redact` 確認 0 finding
- [ ] 5.2 確認 commit message 不含 prod IP / DB password / token / Langfuse secret keys
- [ ] 5.3 /spectra-archive langfuse-sdk-overhead-rca
