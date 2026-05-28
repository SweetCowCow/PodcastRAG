## 1. Baseline diff + regress 名單

- [x] 1.1 跑 `python3 backend/eval/scripts/diff_baselines.py` 對比 `backend/eval/results/baseline-post-judge-v2-2026-05-27.json`（old）vs `backend/eval/results/baseline-stopword-filter-2026-05-28-chat.json`（new），輸出 per-question PASS→FAIL / chunk_recall delta 表。行為：產出 markdown / CSV 報告。驗證：報告檔案落地 `backend/eval/results/diff-stopword-filter-vs-baseline-2026-05-28.md`，包含至少 5 個 chunk_recall regress 題目 + PASS→FAIL 題目（如有）。
- [x] 1.2 列出 audit 名單（≥5 題）：從 1.1 報告挑選 chunk_recall regress 最大 + 含 PASS→FAIL 的題目，記在 case study「Audit 範圍」段。驗證：case study 列出 item id + 對應 design_type + 退步幅度。

## 2. Per-item lexical bridge audit

- [x] 2.1 落實 spec `RCA SHALL produce per-question lexical bridge audit for regress items` 首要 input：對 audit 名單每題抓 query text，本地跑舊版（無 filter）跟新版（含 filter）的 `_build_ts_query`，落地 old/new ts_query 字串對照表。驗證：表格落 case study，每題一 row 含 item_id / question / old_ts_query / new_ts_query。
- [x] 2.2 落實 spec `RCA SHALL produce per-question lexical bridge audit for regress items` 核心 audit：對每題的 GT chunks（從 dataset `extended-multi-turn-40.json` 撈 ground_truth_chunk_ids），用 `mcp__podcastrag-pg__query` 跑兩條 query：對 GT chunk 的 `text_tsvector @@ to_tsquery('simple', old_ts)` matches + ts_rank，跟新版同樣值。驗證：表格落 case study，每 GT chunk 一 row 含 old_match / old_rank / new_match / new_rank。
- [x] 2.3 落實 spec `RCA SHALL produce per-question lexical bridge audit for regress items` 結論：從 2.2 表格統計：多少 GT chunk 是「old=true / new=false」(lexical bridge 被砍)、「old=true / new=true 但 rank 退」、「old=false / new=false 兩端都 miss」。把分佈寫進 case study「Bridge audit 結論」段。驗證：三類分佈數字 + 比例落地。

## 3. Bridge token 分類

- [x] 3.1 落實 spec `RCA SHALL classify bridge tokens removed by the filter` 分類規則：對 2.1 表格內 old_ts → new_ts 砍掉的 token，做三類分類：(a) 真 stop-word（譬如 `的 / 不 / 在`）(b) 內容詞被誤砍（譬如 `想 / 說 / 用 / 提到`）(c) 1-char 信號詞（譬如 `歌 / 酒 / 火 / 習`）。判斷標準寫進 case study。驗證：分類規則段落清楚。
- [x] 3.2 落實 spec `RCA SHALL classify bridge tokens removed by the filter` 統計：三類在所有 audit 題的 aggregate count + 每類一個具體 example token + 該 token 對應的 GT chunk 文字出現位置。驗證：3-row 表格落 case study，每 row 含 category / count / example_token / example_gt_chunk_excerpt。

## 4. ts_rank 分佈分析

- [x] 4.1 對 sample 8 題（含 b20 + 7 個從 audit 名單或隨機抽）用 `mcp__podcastrag-pg__query` 跑 GT chunk 在全 show（scoped by show_id）lexical pool 的 row_number rank 在 old vs new ts_query 的位移。驗證：散佈表落 case study，每 GT chunk 一 row 含 old_rownum / new_rownum / total_old_match_count / total_new_match_count。
- [x] 4.2 對 4.1 結果分類：「rank 提升但 match 消失」（從 K → null）vs「rank 沒提升、match 仍在但被擠掉」（從 K → K+N）vs「rank 從 K → 進 top-50」（成功 case）。寫進 case study。驗證：三類比例落地。

## 5. RRF merge contribution audit

- [x] 5.1 落實 spec `RCA SHALL quantify RRF merge contribution from weak lexical match` 個案測量：從 audit 名單中找出「old: lexical matches=true (rank > 50) + semantic top-K 沒 GT chunk → 最終 chunk_recall 有 GT」這類 case，量該題 GT chunk 在 RRF score 內的 lexical 加成貢獻佔比（從 baseline JSON 的 per-item raw 撈或重新跑 `/shows/{id}/search?debug_trace=true`）。驗證：至少 3 個 case 的 lexical contribution % 落 case study。
- [x] 5.2 落實 spec `RCA SHALL quantify RRF merge contribution from weak lexical match` aggregate 結論：由 5.1 推算「弱 lexical RRF 加成」對整體 chunk_recall 的貢獻 — 譬如「N 個題目 GT chunk 完全靠弱 lexical bridge 進 final top-K，移除後流失 X percentage points」。驗證：quantitative statement 落 case study。

## 6. Follow-up change 候選排序

- [x] 6.1 落實 spec `RCA SHALL produce at least two ranked follow-up change candidates` 候選撰寫：對至少 2 個 follow-up change 候選撰寫 short proposal：候選包含但不限於 `lexical-idf-based-weighting` / `lexical-bridge-preserving-stopword-list` / `agent-prefilter-dispatch-strengthening` / `lexical-bm25-replace-ts_rank`。每個含一段 summary + expected effort (S/M/L) + expected impact direction（chunk_recall delta 估計區間）。驗證：≥2 候選落 case study，每候選 ≥3 句說明。
- [x] 6.2 落實 spec `RCA SHALL produce at least two ranked follow-up change candidates` ROI 排序：對候選做 ROI 排序，top 候選標記為「下一個推薦 propose」。驗證：candidates 表有明確 rank 欄、有單一 top recommendation。

## 7. Case study + 結尾整理

- [x] 7.1 整合 1-6 結果到 `docs/case-studies/lexical-stopword-filter-rca-deep-dive-2026-05-28.md`：含 Background（連到 archived RCA + 訂正段 + 失敗的 stopword-filter change）、5 段分析、結論段、follow-up candidates 排序。行為：case study 是 archive 前最後 audit 證據。驗證：手動 review、確認所有段落齊全、命名單一 root cause 結論 + 下一步推薦。
- [x] 7.2 把舊 parked change `retrieve-hybrid-lexical-stopword-filter` 狀態決議寫進本 case study 末段：選項 (a) 永久 abandon（廢棄）(b) 保留 parked 作為「曾嘗試過」的歷史紀錄。行為：拍板 + 原因紀錄。驗證：case study 有明確決議段。
- [x] 7.3 gitleaks scan：`gitleaks protect --staged --no-banner --redact` 對 staged 檔案跑 0 finding。行為：case study + 任何 staged 檔不洩 secret。驗證：command exit code 0、stdout 顯示 no leaks。
