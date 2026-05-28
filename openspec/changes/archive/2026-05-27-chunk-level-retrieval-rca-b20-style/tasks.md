## 1. 準備 prod DB read-only 連線

- [x] 1.1 取得 prod DB 連線：透過 backend container exec 取得 `psql` access，`PGPASSWORD` 走 env、不入 argv 或 URL（per memory `feedback_subprocess_creds_via_env.md`）。完成時可在 container 內以一條 `SELECT 1;` 驗證連線回 `1`。
- [x] 1.2 確認 `c1d87278-7dba-4fb1-930d-c2bd3a3461d2` 對應的 `transcripts.id` 與 `transcripts.status='completed'`。驗證：單條 SELECT 回傳 1 row 且 status 為 completed；若否，diagnostic 必須 abort 並把 transcript 狀態記入 case study。

## 2. Q1 chunk presence query

- [x] 2.1 落實「Q1 chunk presence query SHALL be executed before any chunking or retrieval code change」：對 `transcript_chunks` 撈 `episode_id=c1d87278-...`、`start_time BETWEEN 1700 AND 2080` 的所有 row，欄位含 `id, start_time, end_time, length(text), segment_ids`。驗證：把完整 result rows 落地到 case study 內 fenced code block，包含 row 數量與每 row `start_time`。
- [x] 2.2 依 Q1 結果做 root cause 分支判定：檢查是否有 row 的 `start_time` 落在 `[1780, 1820]`（或 `end_time` 跨越該區間）。驗證：case study 內明確標記「分支 → A（無 chunk）」或「分支 → B（有 chunk）」，附對應 Q1 row 引用。

## 3. Q2 segment presence query（root cause A 路徑）

- [x] 3.1 若 Q1 路由到 root cause A，落實「Q2 segment presence query SHALL verify whether transcript_segments exist in the gap when root cause A is suspected」：對 `transcript_segments` 撈 `transcript_id=<step 1.2 取得>`、`start_time BETWEEN 1780 AND 1820` 全部 row。驗證：result rows 落地 case study，含 row 數、每 row `start_time` 與 `length(text)`。
- [x] 3.2 依 Q2 結果區分 A1（segments 存在 → chunking aggregation gap）vs A2（segments 缺失 → 上游 ASR gap）。驗證：case study 內以「Root cause = A1」或「Root cause = A2」明確標記，並附 segment_id 樣本作為證據；若 Q1 已路由到 B 則此 group 跳過並在 case study 註記 N/A。

## 4. Q3 RRF reproduction query（root cause B 路徑）

- [x] 4.1 若 Q1 路由到 root cause B，落實「Q3 RRF reproduction query SHALL identify the filter responsible when root cause B is suspected」：把 Q1 撈出且覆蓋 1790 或 1808 的 chunk_id 列出，本地 reproduce `_TRANSCRIPT_RRF_SQL`（位於 `backend/app/services/rag.py` 內的 transcript RRF 管線），用 b20 dataset 對應 question 跑 query。驗證：產生一張表，每 chunk 標 `rank_s`、`rank_l`、`rrf_score`、`tsvector @@ tsquery` 布林值，落地 case study。
- [x] 4.2 依 Q3 結果區分 B-lexical（tsquery 不命中）vs B-cap（命中但 rank 超過 `RRF_PER_SIDE`=50）。驗證：case study 標「Root cause = B-lexical」或「Root cause = B-cap」，附 rank 數字與 query token 證據；若 Q1 路由到 A 則此 group 跳過並在 case study 註記 N/A。

## 5. Case study output 撰寫

- [x] 5.1 落實「Case study output SHALL document evidence, root cause, and fix direction without proposing code changes」：撰寫 `docs/case-studies/chunk-level-retrieval-rca-b20-2026-05-27.md`，含 Background（引 b23 case study）、Q1/Q2/Q3 三段 SQL 全文、實際 row 結果、Root cause 段落（命名 A1 / A2 / B-lexical / B-cap / inconclusive 其一）、Next change recommendation（命名後續 change，如 `chunking-boundary-fix-ep134-style` 或 `retrieve-hybrid-filter-relax`）。驗證：手動 review 確認五段都存在、命名單一 root cause、無任何 prod code patch / fix snippet。
- [x] 5.2 在 case study 末段加 Non-actions 清單，明確列出本 change 未做的事（無 prod code 變動、無 deploy、無 eval baseline 重跑、無 dataset 修改）。驗證：手動 review 該段存在、條列完整。

## 6. Diagnostic execution SHALL NOT modify 守則驗證

- [x] 6.1 落實「Diagnostic execution SHALL NOT modify prod data, prod code, or eval baselines」守則驗證：檢查 shell history / case study 內所有 SQL 皆為 SELECT，無 INSERT/UPDATE/DELETE/DDL；確認本 change 工作期間無 `zeabur deploy`、無 `git push` 觸發 build、無 `.env` 修改。驗證：在 case study 末附「Read-only audit」段落列出所有執行過的 SQL statement 開頭關鍵字皆為 SELECT。
- [x] 6.2 gitleaks scan 確認 case study 不含 secret（per memory `feedback_public_repo_commit_safety.md`），且 case study 內 prod DB host / password 經 redact。驗證：跑 `gitleaks protect --staged --no-banner --redact` 回 0 finding。
