## 1. Stage A — Pipeline I/O Audit before any code change (diagnostic tool design)

- [x] 1.1 寫 `backend/scripts/audit_voyage_pipeline.py`：argparse 接 `--item-ids b21,b22,b23 --backend https://podcastrag-api.zeabur.app --out /tmp/voyage-audit.json --session-cookie-file /tmp/podcastrag_session.txt --me-json /tmp/me_resp.json`。對每 item：(a) 從 dataset 讀 question / ground_truth_chunk_ids_must/either/acceptable，並從 GT chunk_id 反推 expected_episode_uuids（沿用 diagnose_prefilter 的 `_derive_prefilter_episodes` 邏輯，因 dataset 的 `expected_episode_uuids_*` 欄位多為 null） (b) 開跑前先 GET `/me` 驗 200（session 過期則印明確 error 中斷），再 POST query?debug_trace=true 拿 raw trace (c) 從 trace tool_calls 抽 stage 2（args.topic / args.query）跟 stage 3（search_with_topic_prefilter result_full 的 `prefilter_episode_count` / `prefilter_source` / `fallback_to_full_pool`，外加同 trace 內 find_episodes_by_topic enumeration call 若有）跟 stage 5（result_full 的 `rerank_input_count` + `rerank_applied`；doc 為純 text，見 rag_rerank.py:226）。**stage 6-7（voyage raw response / index→chunks mapping）prod trace 不暴露 → verdict 一律 `unknown`，actual=None**（option A 黑箱夾擊；2026-06-04 user 拍板）。stage 7 off-by-one 改靠 rag_rerank.py:249-256 靜態 review 補。 (d) 額外 call `POST /admin/diagnose/prefilter-rank`（body 用 `items` 參數，top_n=30）拿 stage 4 (retrieve_hybrid GT-episode-filtered top-30 + GT rank；注意此為 ideal-prefilter 池，隔離 topic 抽取雜訊) (e) 從 response 的 `citations`（ChunkHit，無 chunk_id → 用 episode_id + start_time ±10s match GT）抽 stage 8-9（grader 直接讀 response.citations，故 stage 9 ≡ stage 8）。**root cause 靠 stage4-in（GT 在池）↔ stage8-out（GT 在 citations）夾擊 + fallback_to_full_pool 判別**。輸出 JSON 跟 markdown table（每階段 expected / actual / verdict）。驗證 = `python -m backend.scripts.audit_voyage_pipeline --item-ids b21,b22,b23 --out /tmp/voyage-audit.json` 跑完且 JSON 內 3 個 item × 9 個 stage 都有 actual + verdict 欄位
- [x] 1.2 跑 audit 對 b21 (control)：refresh session → 跑 audit script → 對照預期。**驗證（對齊 option A，stage 7 已恆為 unknown）= b21 stage 4 (retrieve_hybrid pool) 多數 GT 在 top-30 + stage 8/9 (citation collector / grader-visible citations) 含 ~3 個 GT chunks**（b21 在 prod 已驗 chunk_recall=0.6，must 共 5 chunk → 3/5）。如 b21 control 的 stage 8 拿不到 GT → grader / citation collector 還有別的 bug 要先抓（即 overall_verdict 非 pipeline_ok/voyage_partial_demotion）
- [x] 1.3 跑 audit 對 b22 + b23：refresh session → 跑 audit script → 落地結果到 `docs/case-studies/voyage-rerank-pipeline-audit-2026-05-27.md`。每階段三欄 (expected / actual / verdict)。**驗證 = case study 含 18 列（2 題 × 9 階段）對比**
- [x] 1.4 結論段：根據 Stage A 結果寫 root cause 結論。明確分類：
  - **(a)** 單一階段 drift（指明是哪階段 + 後續 Stage B fix 範圍）
  - **(b)** 多階段 drift（列每個）
  - **(c)** 全階段 match 但 grader 仍給低分（→ root cause = voyage 對中文 long context 排序天然弱、ablation 也救不了；Stage B = revert + negative finding）
  - **(d)** b22 跟 b23 root cause 不同（b22 可能根本沒進 voyage path；要寫成兩條獨立後續）

  驗證 = case study 結論段含 (a)/(b)/(c)/(d) 之一明確判讀 + Stage B 動作清單 + 是否需要 stop-the-line 找 user 拍板

- [x] 1.5 **Stop-the-line gate**：把 Stage A 結論 + Stage B 候選範圍交給 user 拍板 Stage B 動作再繼續。**不能自動進 Stage B**（避免 scope creep）。驗證 = 對話中明確列出 Stage A findings + Stage B 候選 options + 等 user 決定

## 2. Stage B — Targeted fix (Stage B routing — decide after Stage A)

- [x] 2.1 user 拍板 Stage B 範圍後，更新本 change 的 design.md「Implementation Contract」+ spec delta（如有）+ 新增 task 2.2+ 細項到 tasks.md。**這個 task 是 meta — 更新 artifact 本身**。驗證 = design.md「Implementation Contract」段 Stage B 範圍從 placeholder 變成具體 contract；tasks.md 有 ≥ 1 個具體 Stage B 子 task
- [x] 2.2 在 `backend/app/services/episode_finders.py` 的 `_TOPIC_SQL` 加 `ts_rank` 相關度欄位（`GREATEST(ts_rank(title_tsvector, to_tsquery('simple', :tsquery_text)), COALESCE((SELECT max(ts_rank(d.text_tsvector, to_tsquery('simple', :tsquery_text))) FROM episode_description_chunks d WHERE d.episode_id = e.id AND d.text_tsvector @@ to_tsquery('simple', :tsquery_text)), 0))`），改 `ORDER BY relevance DESC, published_at DESC NULLS LAST LIMIT :max_eps`。新增 setting `topic_prefilter_max_episodes`（config.py，default 10，env 可覆寫；≤0 = 不限制 = rollback 舊語意）。`find_episodes_by_topic_with_source` 把 `max_eps` 傳入 params；merged 路徑只 cap topic_eps、guest_eps 全帶。**驗證 = 既有 episode_finders 單元測試綠 + 新增一條測試證明 `topic_prefilter_max_episodes=N` 時 topic_eps ≤ N 且按 relevance 排序**
- [x] 2.3 local 驗證：對 b23 topic「迪拉 Leo王」跑 `find_episodes_by_topic_with_source`（或既有 diagnose endpoint）確認 candidate 從 64 降到 ≤ N 且 EP107（`8b3d4c1d`）仍在候選內。**驗證 = local 印出 candidate 集數 + 確認 GT 集 `8b3d4c1d` 在列**
- [x] 2.4 deploy 到 prod（Zeabur，env 確認 `topic_prefilter_max_episodes` 真值）→ re-run `audit_voyage_pipeline --item-ids b20,b21,b23`。**驗證 = b23 stage 3 candidate count ≪ 64 + b23 stage 8 gt_matched ≥ 1（GT 回 citations）+ b20/b21 stage 8 不退步**；若 EP107 GT 沒回來 → 調 N 或記為 prefilter-cap 不足以解、進 negative finding
- [x] 2.5 b22 拆出：在 `docs/case-studies/` 記 b22 root cause 指針，propose 獨立 follow-up change（routing + distributed-evidence retrieval；與 voyage 無關）。**驗證 = 本 change proposal/design 的 Open Questions 或 follow-up 段含 b22 拆出指針；不在本 change 動 b22 code**

## 3. 最終驗收

- [x] 3.1 重跑 8 題 subset eval（b20/b21/b22/b23/b29/mt02-04）對比 PARTIAL 後的數據（cross_episode chunk_recall 0.283 / factual 0.700）。**Gate**：cross_episode chunk_recall mean ≥ 0.40 且 factual mean ≥ 0.80 → success；否則 negative finding。驗證 = case study 結論段含 gate 明確 PASS/FAIL + per-item before/after table
- [x] 3.2 結論判讀三選一：
  - **PASS**：archive；release log 加 entry
  - **PARTIAL**（某 metric 上某 metric 沒）：archive + propose 下一條 follow-up
  - **REGRESS**（chunk_recall < 0.283 或 factual < 0.700）：revert Stage B commit + 寫 negative finding + 評估下個 lever

  驗證 = case study 結論段含三條判讀路徑都有寫；revert 路徑包含 git revert 指令
