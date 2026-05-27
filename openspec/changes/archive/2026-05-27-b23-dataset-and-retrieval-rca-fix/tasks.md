# Tasks

Per design goals 1–5 + 對齊 design non-goals「不動 agent 代詞解析 / judge / ASR / Voyage rerank」:

## 1. Phase 1 — Dataset audit fix（保留 EP107 GT，移除 EP116 GT，補 b22 三組 either）

對齊 design 決策「Phase 1 dataset audit：保留 EP107 GT，移除 EP116 GT，補 b22 三組 either」+ 對齊 Goals 第一二項。

- [x] 1.1 修 b23 `ground_truth_chunk_ids_must`：從 3 chunks 變 2 chunks（移除 `ep:cb96f6f8-58fb-43fd-bbd6-da1b585d9f60@187.48`，保留 EP107 兩個 chunks）；視 user 拍板把 EP116 那個移到 `ground_truth_chunk_ids_acceptable` 或完全移除；對應 spec ADDED Requirement「Chunk-level GT audit SHALL verify pronoun reference matches the question's subject」Scenario 1
- [x] 1.2 修 b23 `audit_notes` 加 entry：列每個 must chunk 的主體判斷（譬如「EP107 @1766.87: 迪拉自述在 Live house 看表演被 Leo 王主動自我介紹；主體 = 迪拉↔Leo 王 ✓」）；對應 spec Scenario「Audit note records pronoun-reference verification result」
- [x] 1.3 補 b22 `ground_truth_chunk_ids_either` 三組（杜宗祐 / 方品融 / 阿名 各一組 evidence chunks）；用 `POST /shows/{id}/search` 重撈每個名字的代表 chunks 然後寫進 dataset；ASR 錯字「杜忠祐」用 ASR 實際儲存名標記（per design non-goal「不修 ASR」）；對應 spec ADDED Requirement「Distributed evidence questions SHALL use the `either` tier rather than empty must」Scenario 1
- [x] 1.4 修 b22 `audit_notes` 寫評分邏輯（譬如「杜宗祐 5 chunks 在 EP119/EP52/EP122/EP87/EP130；方品融 2 chunks 在 EP94；阿名 1 transcript + 3 description chunks；either 結構讓任一組命中即算」）
- [x] 1.5 寫 audit script `backend/eval/scripts/dataset_audit_b22_b23.py`：local 用，列出修改前後 diff、jq-style 印 b22 / b23 的 must / either / acceptable 三層 GT chunks 變化、印 audit_notes 變動

## 2. Phase 2 — `find_episodes_by_topic` guest 索引 dispatch（啟發式 + envelope 揭露 source）

對齊 design 決策「Phase 2 guest 索引 dispatch：啟發式 + envelope 揭露 source」+ Goals 第三四項。

- [x] 2.1 在 `backend/app/services/episode_finders.py` 加 helper `_known_guest_names(db, show_id) -> set[str]`：query `episodes.guests` JSONB 收集所有 distinct guest name；用 LRU cache（per show_id）避免每 query 重查
- [x] 2.2 在 `find_episodes_by_topic` 加判斷分支：jieba 拆完 topic_terms 後計算 token ∩ known_guest_names；若 ≥ 2 命中則加跑 guest-index SQL（`episodes.guests @> ANY(...)::jsonb[]` 或對等實作），結果與既有 title/description tsquery 路徑做 union 去重；對應 spec ADDED Requirement「`find_episodes_by_topic` SHALL dispatch to a guest-index path when topic tokens match known guest names」Scenario 1
- [x] 2.3 保留 single-token / zero-match path 行為（不觸發 guest 索引）；對應 spec Scenarios 2 + 3
- [x] 2.4 加 env flag `ENABLE_GUEST_DISPATCH`（default True）允許 rollback toggle 不用重 deploy（per design Migration Plan rollback strategy）
- [x] 2.5 在 `backend/app/services/chat_agent/tools.py` 內 `_search_with_topic_prefilter`：接 `find_episodes_by_topic` 多 return 一個 `source` enum（`topic_index` / `guest_index` / `merged`）；組進 envelope `prefilter_source` 欄位；對應 spec ADDED Requirement「`search_with_topic_prefilter` envelope SHALL expose `prefilter_source` for observability」3 個 Scenario
- [x] 2.6 寫 `backend/tests/test_episode_finders_guest_dispatch.py`：3 個 scenario（2 tokens 觸發 / 1 token 不觸發 / 0 token 不觸發）+ fixture 用 in-memory SQLite 或 fixture db
- [x] 2.7 寫 `backend/tests/test_search_with_topic_prefilter_envelope.py`：3 個 scenario 驗 envelope `prefilter_source` 三態

## 3. Phase 3 — Retrieve_hybrid chunk-level diagnostic（先 audit 不動 code）

對齊 design 決策「Phase 3 retrieve_hybrid diagnostic：先 audit 不動 code」+ Goals 第五項；對齊 non-goals「不動 chunking / embedding code」。

- [x] 3.1 擴 `backend/app/api/admin/diagnose_prefilter.py`：`top_n` 上限從 200 改 500；新 query param `include_chunking_context: bool`，True 時對每個 GT chunk 額外 fetch 前後 2 個 chunks 的 `text` / `start_time` / cosine sim vs query embedding；新 query param `items` 取代 hard-coded `mini_set_ids`
- [x] 3.2 對 b20 跑 `POST /admin/diagnose/prefilter-rank` body=`{"items":["b20"],"top_n":500,"include_chunking_context":true}`，落盤 `/tmp/b20_rank500.json`
- [x] 3.3 對 b23 跑同樣 endpoint body=`{"items":["b23"],"top_n":500,"include_chunking_context":true}`，落盤 `/tmp/b23_rank500.json`
- [x] 3.4 分析 b20 GT @1790.18 / @1808.78：看 top-500 rank、前後 chunks text、cosine sim vs query — 判斷 chunking 邊界 / embedding 對齊 / lexical weight 哪個是 root cause
- [x] 3.5 分析 b23 EP107 GT @1766.87 / @1819.35：看 top-500 rank、前後 chunks text、cosine sim — 判斷同上
- [x] 3.6 寫 `docs/case-studies/b23-retrieval-diagnostic-2026-05-27.md`：含 b20 + b23 top-500 rank 分布表、前後 chunks 對照、root cause 判定、follow-up change 建議（chunking / embedding / lexical 哪個動）；不入 git per memory case studies 不 commit 規則

## 4. Phase 4 — 部份題重跑驗證範圍（只跑變動題 + 對照題）

對齊 design 決策「Phase 4 重跑驗證範圍：只跑變動題 + 對照題」。

- [x] 4.1 對 prod backend RUNNING commit（含 Phase 2 deploy 後）用 `python -m backend.scripts.run_chat_agent_eval_v2 --filter-ids b20,b21,b22,b23 --output backend/eval/results/baseline-post-b23-fix-<DATE>.json --report .../*.md --prod-commit <new-commit> --force` 重跑 4 題
- [x] 4.2 對 b21（控制組）+ 隨機抽 4 題 deep_dive（譬如 b14 b15 b16 b17）重跑確認沒 regress；落同個 baseline JSON
- [x] 4.3 用 `backend/eval/scripts/diff_baselines.py` 對舊 baseline `baseline-post-citation-fix-2026-05-27.json` 跟新 baseline 出 diff 表
- [x] 4.4 寫 diff 結果 + 結論進 case study `b23-retrieval-diagnostic-2026-05-27.md` 附錄（不入 git）

## 5. Phase 5 — 部署 + Smoke

- [x] 5.1 git commit Phase 1 dataset 變動（單獨 commit message 標 `feat(eval-dataset): b22/b23 GT audit fix`）
- [x] 5.2 git commit Phase 2 episode_finders + chat_agent tools 變動（單獨 commit message 標 `feat(retrieval): guest-index dispatch for find_episodes_by_topic`）
- [x] 5.3 git push + Zeabur backend / worker / dispatcher / beat 4 service redeploy（per memory `feedback_zeabur_webhook_unreliable.md` 先 push 看 webhook 觸發，沒觸發則 `service redeploy --id <svc> -y -i=false`）
- [x] 5.4 對 prod 跑 smoke：對「迪拉跟 Leo 王怎麼從不認識變成合作夥伴」query，verify envelope `prefilter_source=guest_index` 或 `merged` + `prefilter_episode_count ≤ 10` + 候選集含 EP107 + EP116
- [x] 5.5 等 deploy 完成 RUNNING 後跑 Phase 4 重跑驗證

## 6. 收尾 + 路線圖同步

- [x] 6.1 更新 `project_pending_changes.md`：archive 本 change 後加進「最近 archive」表，標 b23 三層 + retrieval diagnostic 結論
- [x] 6.2 同步 `docs/roadmap.md`（per `feedback_roadmap_dual_write.md`）：把「b23-dataset-and-retrieval-rca-fix」從衍生待 propose 移到已完成；Phase 3 diagnostic 結論若指向特定 follow-up（chunking / embedding / lexical）則加入待 propose 清單
- [x] 6.3 release log 草稿（per `feedback_release_log_maintenance.md`），用「我們從一題對話 mode 答錯案例挖出 4 層連鎖問題並修了 dataset + retrieval」這個敘事，含 b23 user 親自聽逐字稿的 audit 故事
- [x] 6.4 跑 `spectra validate b23-dataset-and-retrieval-rca-fix` 全綠 + `spectra analyze` 全 clean
- [x] 6.5 `spectra archive` 前確認 Phase 3 diagnostic 結論寫完整 + Phase 4 重跑 chunk_recall ≥ 0.33 達標
