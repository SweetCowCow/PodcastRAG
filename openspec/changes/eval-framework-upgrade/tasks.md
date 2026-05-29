## 1. Phase 1 — Langfuse Cloud Free 接入 + PG eval_traces table + tracing infra

- [x] 1.1 申請 Langfuse Cloud Free 帳號：(a) user 去 cloud.langfuse.com 註冊（可用 Google SSO with `ssweetcoww@gmail.com`）(b) 建 organization + project（建議 project 名 `podcastrag-eval`）(c) 拿到 `pk-lf-*` / `sk-lf-*` keys 走 `feedback_secret_handoff_via_file.md` SOP（user 建空檔 paste、我 `cat` 灌進 backend/.env、跑完問是否刪檔，secret 全程不出現在 chat）。驗收：env file 含三個 key（PUBLIC / SECRET / HOST），任一 backend 進程啟動 `import langfuse; print('ok')` 不噴錯。
- [ ] 1.2 alembic migration 加 `eval_traces` table（schema 見 design Decision 2，雙寫保留 per Decision 1a）；prod 跑 `alembic upgrade head` 後 MCP query `\d eval_traces`-equivalent 驗 schema 含 23 個欄位 + 3 個 index（span_id PK、span identity 4 / timing 3 / LLM-specific 6 / tool-specific 4 / stage 1 / meta 1 = 19 + 4 identity 欄位）。
- [x] 1.3 新增 `backend/eval/tracing/langfuse_setup.py` — `init_langfuse()` 讀 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` env + 提供 `@observe` decorator re-export。Settings 物件加對應 3 個 field（per `feedback_pydantic_settings_extra_forbid_leaks.md` 紀律確保 `extra="ignore"`）。`LANGFUSE_HOST` 預設值 `https://cloud.langfuse.com`。
- [x] 1.4 新增 `backend/eval/tracing/span_writer.py` — `write_span(span_dict)` 寫 PG `eval_traces` table；try/except wrap、失敗 log warning 不 raise。async-safe（用 asyncpg connection pool）。PG insert 跟 Langfuse SDK upload 平行（兩個獨立 try/except）。
- [x] 1.5 修 `backend/app/services/chat_agent/agent.py` — agent loop 入口加 `@observe` decorator；per LLM call + per tool dispatch 包 span context（用 Langfuse SDK + 同步 call `span_writer.write_span`）。env flag `EVAL_TRACING_ENABLED` gate（per spec eval-observability scenario「prod user traffic does not emit spans by default」）。
- [x] 1.6 修 `backend/app/services/chat_agent/tools.py` — `_dispatch_tool` 捕 (tool_name, tool_args, tool_result_chunks, search_query) → span attributes。`search_*` tool 從 `tool_args["query"]` 抽出 `search_query` column 值。
- [ ] 1.7 修 backend 4 service env（backend / worker / dispatcher / beat）：加 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST=https://cloud.langfuse.com` + `EVAL_TRACING_ENABLED=false` 預設關閉。走 `feedback_zeabur_variable_create_dumps_env.md` SOP（redirect stdout 防 env dump 印進 chat）。redeploy + 等 RUNNING（用 `feedback_zeabur_deploy_monitor_pattern.md` 模板）。**無 Zeabur 新 service 部署**，純設 env。
- [ ] 1.8 對 prod 跑單一 chat agent query（admin session + `EVAL_TRACING_ENABLED=true` 暫時 override 或本機 runner 跑）→ 驗證 (a) **Langfuse Cloud Web UI**（cloud.langfuse.com 登入後）看到 trace tree (b) PG `SELECT COUNT(*) FROM eval_traces WHERE run_id='<X>'` ≥ 3 spans (c) 兩邊 span_id 對得齊。

## 2. Phase 2 — DeepEval 4 grader + entity recall + plugin loader 整合

- [ ] 2.1 新增 `backend/eval/graders/answer_relevancy.py` — wrap DeepEval `AnswerRelevancyMetric`；grader plugin interface (`grade(item, response, judge_verdict) -> {score, passed, details}`)；LLM 失敗時回 `{score: null, passed: false, details: {error: ...}}`。
- [ ] 2.2 新增 `backend/eval/graders/contextual_precision.py` — wrap DeepEval `ContextualPrecisionMetric`；同 interface。
- [ ] 2.3 新增 `backend/eval/graders/answer_similarity.py` — wrap DeepEval `AnswerSimilarityMetric`；同 interface。
- [ ] 2.4 新增 `backend/eval/graders/faithfulness_deepeval.py` — wrap DeepEval `FaithfulnessMetric`；同 interface。（命名加 `_deepeval` suffix 避免跟既有 `factual_correctness` 混淆）
- [ ] 2.5 新增 `backend/eval/graders/context_entity_recall.py` — DeepEval `GEval` custom rubric 自寫 entity 抽取 + recall 計算；rubric prompt 清楚列舉 entity types (people / episode title / song / album / book / organisation)；回 `entities_found / entities_total` 比例。
- [ ] 2.6 修 `backend/eval/graders/loader.py` — `discover_graders()` 自動發現新 5 個 grader（既有 plugin 機制，理論上不用改但要驗）。
- [ ] 2.7 修 `backend/eval/judge_chat_v2.py` — 呼叫新 5 grader 加入 indicators dict；既有 6 grader 邏輯不動。
- [ ] 2.8 修 `backend/eval/runner_v2_aggregate.py` — `aggregate()` 函式自動把新 indicators 加進 `by_indicator` dict（既有 plugin 化 aggregate 應該不用改但要驗）。
- [ ] 2.9 對 8 題 calibration set 跑一次 chat eval → 驗證 (a) result file `indicators` 含 11 個 entry (b) 4 個 DeepEval grader + entity recall 都非 null。

## 3. Phase 3 — Episode-scoped retrieval probe CLI + Prompt fingerprint diff CLI

- [ ] 3.1 新增 `backend/eval/datasets/_calibration_8.json` — 從 `extended-multi-turn-40.json` 挑 8 題覆蓋 design_type spectrum（建議：b01 show_overview / b06 guest_find / b08 topic_find / b11 date_find / b18 deep_dive EP-ref / b20 cross_episode / b27 negative / mt03 multi_turn）。SHA256 verify 每題 byte-equivalent。同時更新 `backend/eval/datasets/README.md` 加 calibration set 段落。
- [ ] 3.2 新增 `backend/eval/scripts/retrieve_probe.py` — argparse `--show_id --episode_id --query --top_k`；import `app.services.rag.retrieve_hybrid` 跑 with `episode_id_filter`；印 top-k ranked chunks（chunk_id / start_time / rrf_score / GT 標註）；對 b18 EP44 + query 「伴手禮 現吃好吃 食物」跑驗證、確認 stdout 含 GT marker。
- [ ] 3.3 新增 `backend/eval/scripts/prompt_fingerprint_diff.py` — argparse `--old-commit --new-commit --dataset`；對兩個 commit 各跑 chat eval（透過 `--backend-old/--backend-new` URL 對應已 deployed prod commit，或自動 wait deploy）→ SQL query `eval_traces` 抓 `search_query` per (item_id, turn_idx) → 印 markdown diff 表（item / turn / old_query / new_query / changed?）。
- [ ] 3.4 dry-run 驗證 `retrieve_probe.py`：對 archived `step1-idf-and-prefilter` 的 IDF-bucketed SQL 跟 legacy `ts_rank` 對同一 b18 query + EP44 各跑 → 應印出 episode-scoped ranking 差異（驗證若當時有此工具，IDF 失敗能事前抓到）。結論寫進 case study。
- [ ] 3.5 dry-run 驗證 `prompt_fingerprint_diff.py`：對 archived Layer B 兩個 commit（`c0149ff` revert 後 vs `0e38b16` Layer B 上）跑 → 應抓到 EP-ref query 的 search_query 字面變化（驗證若當時有此工具，Layer B 失敗能事前抓到）。結論寫進 case study。

## 4. Phase 4 — 結合驗證 + PR template 軟約定

- [ ] 4.1 對全 34 題 chat baseline 跑新 pipeline → 對比舊 `baseline-post-judge-v2-2026-05-27.json`：既有 6 grader score per-item 在 floating-point tolerance 內一致；新 5 grader score 全部非 null。落地 `backend/eval/results/baseline-eval-framework-upgrade-2026-05-XX-chat.json`。
- [ ] 4.2 加 PR template section（`.github/PULL_REQUEST_TEMPLATE.md` 或專案 markdown convention）：「Retrieval change checklist」含跑 `retrieve_probe.py` + 貼結果；「Prompt change checklist」含跑 `prompt_fingerprint_diff.py` + 貼結果。
- [ ] 4.3 在 `docs/runbooks/` 寫 `eval-framework-upgrade-runbook.md`（不入 commit per 慣例）：操作員怎麼跑 probe / fingerprint diff / 看 Langfuse UI / SQL audit eval_traces，含常見 RCA query 範例。
- [ ] 4.4 prod 灰度測：對一段時間 prod chat user 流量 toggle `EVAL_TRACING_ENABLED=true` 觀察 P95 latency 增量 **< 100ms**（含 Cloud SDK HTTP 往返到 cloud.langfuse.com 的額外延遲，比自架 ~50ms 容忍度寬鬆，per design Risks 表）；若達標可考慮 default 開；不達標關掉 + 寫 follow-up「優化 span_writer 寫入 P95 / 評估自架降低 SDK 延遲」。同時對 cloud.langfuse.com → Settings → Usage 看實測 units 消耗、跟 ~10 units/trace 估算對校。

## 5. Phase 5 — Case study + memory + roadmap

- [ ] 5.1 寫 `docs/case-studies/eval-framework-upgrade-2026-05-XX.md`：含 (a) Background 連回 step1-idf-and-prefilter 失敗教訓 (b) Phase 1-4 全程紀錄 (c) Langfuse + DeepEval + 5 grader + 2 CLI 部署結果 (d) dry-run 對 archived 失敗 case 的驗證結論 (e) follow-up 建議。
- [ ] 5.2 更新 memory：(a) `feedback_idf_show_wide_failed_2026_05_28.md` 加「現有 retrieve_probe.py 可預先驗證 episode-scoped ranking」follow-up 段 (b) `feedback_prompt_change_retrieval_side_effect.md` 加「現有 prompt_fingerprint_diff.py 可預先驗證 query 字面 drift」follow-up 段 (c) `feedback_show_wide_probe_false_positive.md` 同步更新 (d) `project_pending_changes.md` + `project_pending_change_candidates.md` 標 BM25 / EP-scoped IDF 可重新開始討論（已有觀察工具）(e) `project_langfuse_cloud_free_track_usage.md` 加實測 baseline（真實 units/trace、第一週用量）替換掉估算數字（per `feedback_no_guessed_numbers_from_memory.md` 紀律）。
- [ ] 5.3 更新 `docs/roadmap.md`：標 eval-framework-upgrade ✅ + 解凍 BM25 / EP-scoped IDF 候選 + Langfuse 服務列進部署狀態表。
- [ ] 5.4 release log entry：tag `enhancement`，bilingual zh/en，使用者視角講「內部評分基準升級、新增 5 個品質指標 + trace 可觀察性，未來 retrieval / prompt 改動 RCA 速度顯著加快」。

## 6. Gitleaks + commit hygiene

- [ ] 6.1 每階段 commit 前跑 `gitleaks protect --staged --no-banner --redact` ✅ 確認 0 finding。Langfuse env 變數加 backend/.env 走 user 給 secret SOP（per `feedback_secret_handoff_via_file.md` 走檔案不走 chat）。
- [ ] 6.2 確認 commit message 不含 prod IP / DB password / token / Langfuse secret keys（per `feedback_public_repo_commit_safety.md`）。
