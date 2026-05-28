## Problem

2026-05-28 ship `retrieve-hybrid-lexical-stopword-filter`（commit `01f04a4`）以 stop-word filter + 1-char drop 修 lexical pool noise flood。Prod DB probe 顯示 b20 query lexical pool 從 39,323 → 297（132x 收縮看似成功），但 chat baseline 全面退步：

- `chunk_recall_grouped`：0.482 → **0.390**（-0.092，目標 ≥ 0.55 沒達到、且退步）
- `factual_correctness`：0.892 → **0.839**（-0.053）
- `count_consistency`：1.000 → **0.500**

已 revert prod 至 commit `2ac1ccf`。對應 baseline 結果落地：`backend/eval/results/baseline-stopword-filter-2026-05-28-chat.json`。

## Root Cause

來自 2026-05-28 prod DB probe 實證：b20 GT chunk `9543a933` 文字「就覺得這裡是我的安身之處 ...」對舊 OR query（含 `的 / 不 / 在 / 為 / 什麼`）`matches=true`、ts_rank=0.0059（弱信號）；對 filtered query（只剩 `迪拉胖 | EP134 | 振奮 | 開工歌 | 概念`）`matches=false`。

關鍵發現：**在 OR-joined tsquery + ts_rank + RRF merge 機制下，stop-word 是 GT chunk 命中 lexical pool 的「唯一橋樑」**。即使 ts_rank 弱、被 noise 淹沒、進不了 top-50，它仍讓 RRF merge 把 GT chunk 跟 semantic rank 做 reciprocal-rank 加成。一刀切後 GT 完全不 match，semantic 側單獨撐效果差很多。

這個 root cause 是初步假設。本 change 要跑完整 diagnostic 確認 root cause 範圍 + 量化 + 找替代修法方向。

## Proposed Solution

純 diagnostic change（**不動 prod code**），跑五段分析，產出 RCA case study 跟下一步 change 建議：

1. **Per-question diff 跟 regress 名單**：跑 `diff_baselines.py` 對比 `baseline-post-judge-v2-2026-05-27.json`（old）vs `baseline-stopword-filter-2026-05-28-chat.json`（new），列 PASS→FAIL 跟 chunk_recall 退步的具體題目
2. **每個 regress 題的 lexical bridge audit**：對 regress 名單每題抓 GT chunk text + new ts_query + old ts_query，用 prod DB probe 看 GT chunk 對兩 query 的 `matches=true/false` + ts_rank delta
3. **Bridge token 分類**：分三類：(a) 真 stop-word 純偶然命中（safe to drop）(b) 內容詞但被誤砍（譬如 `想 / 說 / 用` 這類動詞）(c) 1-char 信號詞（譬如 `歌 / 酒 / 火 / 習`），統計各類比例
4. **ts_rank 分佈分析**：對 sample 8 題（含 b20 + 7 隨機）量「GT chunk 在 lexical pool 的 rank 在 old vs new 的位移」 — 區分「rank 提升但 match 消失」vs「rank 沒提升、match 仍在但被擠掉」
5. **RRF merge contribution audit**：量「lexical=0 vs lexical>0」對 final top-K 的 GT chunk recall 差異 — 證實 stop-word 作為 lexical bridge 對 RRF 加成的具體量級

## Non-Goals

- 不改 prod code（任何修法走後續 change）
- 不重 retrieve / RRF / chunking / embedding 任何層
- 不修 golden set / GT chunk_id
- 不 archive `retrieve-hybrid-lexical-stopword-filter`（per migration plan「退步 → 不 archive」；本 RCA 跑完後再決定如何處置那個 parked change）
- 不寫 design.md（pure diagnostic、無新架構決策）

## Success Criteria

- 產出 case study `docs/case-studies/lexical-stopword-filter-rca-deep-dive-2026-05-28.md` 含 5 段分析結果
- 列出至少 5 個 regress 題的 GT chunk lexical bridge audit
- 量化 bridge token 三類比例
- ts_rank 分佈散佈圖 / 表格（CSV / markdown 都可）
- RRF lexical contribution 量級結論（譬如「lexical 弱 match 對 GT recall 的 reciprocal-rank 加成平均貢獻 X%」）
- case study 末段列出**至少 2 個 follow-up change 候選**並排序 ROI，譬如：
  - `lexical-idf-based-weighting`（用 corpus token frequency 做 IDF 降權，取代 hard stop-word filter）
  - `lexical-bridge-preserving-stopword-list`（細選 stop-word list，保留作 RRF bridge 的常用詞、只砍真噪音）
  - `agent-prefilter-dispatch-strengthening`（從 retrieve_hybrid 改良路線跳出，改強 agent 端 prefilter dispatch）
  - `lexical-bm25-replace-ts_rank`（換 PG ts_rank → BM25 with IDF）

## Impact

- Affected specs: 無
- Affected code: 無 prod code 變動
- Affected ops: 純 prod DB read-only probe（走 `mcp__podcastrag-pg__query`，sample <100 row）+ local diff_baselines 跑分
- Risk: 低 — 純 diagnostic、無寫入、無 redeploy
