# Tasks

## 1. Pre-flight：prod backend 對齊 + smoke（design 決策「用 prod backend（含 `287e73b`）而非 local backend」）

- [x] 1.1 用 `zeabur deployment list --service-id 69eb10360da29f05f49a4b0b` 確認 backend RUNNING commit ≥ `287e73b`（含 `_AGENTIC_SEARCH_TOOLS` 漏 `search_with_topic_prefilter` 的 citation collector fix）；不符則 abort + 通知 user 先 redeploy。對齊 goals 第一項「對 prod backend 跑乾淨 baseline」
- [x] 1.2 確認 `~/.config/podcastrag/e2e-token` 有效，對 `https://podcastrag-api.zeabur.app/me` curl 回 200；過期則跑 E2E backdoor /tmp HTML redirect SOP 重新拿 cookie 到 `/tmp/podcastrag_session.txt`
- [x] 1.3 對 b20 跑一發 chat query（透過 `/query?debug_trace=true` admin 模式），確認回傳的 `citations` 陣列非空且至少含 1 個 chunk_id，證明 prefilter 路徑下 citation collector 真的有撿到 chunks（若空 → 表示 fix 沒生效 → abort）

## 2. 落盤 baseline 撈舊資料

- [x] 2.1 在 `backend/eval/results/` 找 2026-05-26 / 2026-05-27 期間產的 chat-rag baseline JSON，複製到 `backend/eval/results/_polluted-baselines/` 暫存區做 diff 對照來源；若 git untracked 且本地沒檔則記「舊資料 partial missing」改用 case study 抄寫的 aggregate 對照（per design non-goals「不重新 archive 舊 change」）
- [x] 2.2 在 case study 草稿頂端列出 commit 時間軸：`1c6e311`（prefilter 引入）→ `255f7a5`（multi-turn fix）→ `c93e395`（cross-episode recall sweep）→ `924c8ef` + `336c69d`（Voyage）→ `287e73b`（citation fix），標明每個 archive 的 baseline 數據都在 `1c6e311` 之後到 `287e73b` 之前的「污染期」

## 3. Runner 加 provenance metadata（實作 spec ADDED Requirement「Baseline result files carry provenance metadata」）

- [x] 3.1 在 `backend/eval/run_chat_agent_eval.py` 加 `_collect_provenance()` helper：呼叫 `GET /admin/version`（若無則改用 `git ls-remote https://github.com/<repo> HEAD` 或 CLI flag `--prod-commit`）拿 backend commit；組 `{backend_commit, dataset_path, dataset_schema_version, run_started_at, run_completed_at, citation_collector_fix_applied}` dict（對應 Baseline result files carry provenance metadata Scenario 1）
- [x] 3.2 將 `citation_collector_fix_applied` 推導邏輯寫死：若 commit 等於或晚於 `287e73b`（用 `git merge-base --is-ancestor 287e73b <commit>` 判定）則 True；判定失敗則 fallback 用 runner CLI flag `--citation-fix-confirmed` 顯式宣告
- [x] 3.3 在 baseline JSON 寫盤點同時 emit `provenance` 區塊到 top-level（含 partial-write 路徑：abort handler 也要寫，對應 Baseline result files carry provenance metadata Scenario 2）
- [x] 3.4 加 `--force` flag；不帶且輸出檔已存在則 exit 非零並印「existing baseline at <path>; pass --force to overwrite」（對應 Baseline result files carry provenance metadata Scenario 3）
- [x] 3.5 寫 3 個 pytest unit test 對應 spec 三個 scenario：full run provenance / partial run provenance / overwrite refusal

## 4. 跑乾淨 baseline（design 決策「baseline 落盤命名 + 路徑」+「skill 紀律」）

- [x] 4.1 用 `rag-eval-runner` skill 進入持久化 runner（nohup + stdbuf -oL + PID 紀錄，對應 design 決策「skill 紀律」）；preflight + canary 通過後跑全 40 turn 對 prod
- [x] 4.2 監看 log：tail `nohup.out`，每 5 turn 印一次進度；若 60 秒沒新行則檢查 PID 還活著、prod 是否 5xx
- [x] 4.3 結果落盤 `backend/eval/results/baseline-post-citation-fix-<YYYY-MM-DD>.json`（對應 design 決策「baseline 落盤命名 + 路徑」），jq 驗：`.provenance.backend_commit` / `.provenance.citation_collector_fix_applied == true` / `.aggregate.chunk_recall_grouped` 都非 null
- [x] 4.4 對 cross_episode design_type 4 題（b20 / b21 / b22 / b23）的 `citations` 陣列各自非空；若任一為空 → 部署可能有 race，重跑該 record

## 5. Per-question diff 表（design 決策「per-question diff 表呈現方式」）

- [x] 5.1 寫 ad-hoc Python script `backend/eval/scripts/diff_baselines.py`（local 用，不入 spec）：吃舊 + 新兩個 JSON，輸出 Markdown 表，欄位 `record_id` / `turn_index` / `question`（截 60 字） / `design_type` / `chunk_recall_old` / `chunk_recall_new` / `factual_old` / `factual_new` / `Δ_chunk_recall` / `Δ_factual` / `verdict`（improved / regressed / unchanged / data_missing）
- [x] 5.2 對 cross_episode 4 題另起放大鏡 section：列出每題的 question 全文、expected episodes、新 baseline top-5 chunks 的 episode_id 與 score、GT chunks 命中第幾名（若未命中標 ✗）
- [x] 5.3 design_type aggregate 對照表：6 個 design_type × `chunk_recall_grouped` / `factual` / `refusal_appropriateness` 的舊 vs 新 mean
- [x] 5.4 「已 archive change 結論需 revise 清單」：列 `retrieval-cross-episode-chunk-recovery`（NEGATIVE finding 重評）、`retrieval-cross-episode-episode-prefilter`（持平結論重評）、`retrieval-rerank-via-voyage`（PARTIAL 數據真實基準對齊）三條，各寫一段「原結論 → 用新 baseline 後該結論是否還站得住」

## 6. Case study 落地

- [x] 6.1 撰寫 `docs/case-studies/eval-baseline-citation-bug-revalidation-<YYYY-MM-DD>.md`：含污染時間軸 / 範圍 / 修正 commit / per-question diff 表 / cross_episode 4 題放大鏡 / design_type aggregate / archive change 影響清單 / next-step 指針給 `voyage-rerank-tune-b22-b23`
- [x] 6.2 標 docs/case-studies/ 不入 git commit（per memory `feedback_case_studies_no_commit.md`）；但 backend/eval/results/ 的 baseline JSON 入 git，case study 引用其 commit hash

## 7. Memory + 路線圖同步

- [x] 7.1 更新 `project_pending_changes.md`：當前部署狀態段加「baseline-post-citation-fix-<日期> 為新乾淨基準；舊 0.244 deprecated」；最近 archive 表加註本 change
- [x] 7.2 同步 `docs/roadmap.md`（per memory `feedback_roadmap_dual_write.md`）
- [x] 7.3 寫 release log 草稿（per `feedback_release_log_maintenance.md`），問 user 要不要進 release log

## 8. 收尾（design 決策「是否需要重跑 judge」確認 + non-goals 校對）

- [x] 8.1 在 case study 末段預告 `voyage-rerank-tune-b22-b23` Stage A 可直接 fork 本 change 的 per-question 表做對照，省一輪 baseline 重跑
- [x] 8.2 對齊 design 決策「是否需要重跑 judge」— 本次只重跑 runner / grader，不重跑 judge prompt；確認 case study 沒誤導讀者以為 judge 也重評
- [x] 8.3 對齊 design non-goals 一遍：沒跑 semantic / keyword 模式、沒動 dataset、沒重 archive 舊 change、沒做 b22/b23 root cause（那留給下個 change）
- [x] 8.4 跑 `spectra validate eval-baseline-citation-bug-revalidation` 全綠
- [x] 8.5 `spectra archive` 前先問 user：cross_episode 4 題的「verdict」是否需要 user 二次確認
