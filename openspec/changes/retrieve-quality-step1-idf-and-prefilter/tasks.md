## 0. Outcome — 2026-05-28 FAILED, both layers reverted

> **STATUS**: ❌ FAILED. Layer A (commit aea7590) reverted at d5d1a59 + forward-fix c0149ff. Layer B (commit 0e38b16) reverted at d74eecd. See `proposal.md` Outcome section + `design.md` Postmortem + `docs/case-studies/retrieve-quality-step1-idf-and-prefilter-2026-05-28.md`.
>
> Tasks below marked [x] reflect "shipped + measured", not "succeeded". Each Layer section ends with a 達標判定 row showing why it failed.

## 1. Layer A — IDF infrastructure（migration + cache module）

- [x] 1.1 alembic migration 新增 `transcript_token_freq` table — prod 已 ship（commit bf1e4df，後 forward-fix c0149ff 保留檔案避免 alembic_version 對不齊）。orphan table 保留在 prod。
- [x] 1.2 `backend/app/services/lexical_idf.py` 新增 `refresh_freq_table` — prod backfill 3 shows / 247K tokens / 142K docs / 10.8s。（隨 revert d5d1a59 刪除）
- [x] 1.3 `get_idf_buckets` + `build_bucketed_ts_queries` — bucket 分布 A 90%+ / B 6-9% / C 1% / D < 0.1%。（隨 revert 刪除）
- [x] 1.4 admin endpoint `POST /admin/lexical-idf/refresh` — prod curl 200 + JSON。（隨 revert 刪除）

## 2. Layer A — Lexical SQL 改 IDF weighting（rag.py）

- [x] 2.1 `_TRANSCRIPT_RRF_SQL` 改成 bucketed weighted sum。Decision A2 apply 階段已修訂（原 `ts_rank_cd` weight array PG 語意不通，改 multi-bucket sum）。（隨 revert 刪除）
- [x] 2.2 IDF lookup try/except fallback 到 legacy `_TRANSCRIPT_RRF_SQL`。實際 prod 從未觸發 fallback。（隨 revert 刪除）
- [x] 2.3 合併到 3.2 prod DB probe。

## 3. Layer A — Prod backfill + verify

- [x] 3.1 `POST /admin/lexical-idf/refresh?all=true` ✅ 3 shows / 每 show > 70K tokens。
- [x] 3.2 b14 prod DB probe 結果：GT chunk `405a7b8c` 在 bucketed pool **#1**；高 IDF 桶 chunks (含「振奮」) avg rank 0.062 vs 只命中「什麼」(D bucket) chunks avg 0.0033 — **19x ratio**。**show-wide pool 內** spec scenario「high-IDF rank earlier」確實成立。
- **隱性 false positive 教訓**：show-wide pool 內成立的「high-IDF 優先」效果，在 chat agent 實際 `search_within_episode`（帶 `episode_id_filter`）的 ~30 chunk 小池內**反向作用** — 因為 episode 內 topic 詞滿地都是，bucketed weight 把 topic-related-but-not-answer chunks 排到前面。

## 4. Layer A — Baseline run（only A）

- [x] 4.1 chat baseline only-A → `backend/eval/results/baseline-step1-idf-only-2026-05-28-chat.json`。
- [x] 4.2 diff → `backend/eval/results/diff-step1-idf-only-vs-baseline-2026-05-28.md`。
- [x] 4.3 **Layer A 達標判定：FAIL** — chunk_recall_grouped 0.482 → 0.382 (-0.100) / factual 0.892 → 0.831 (-0.061) / 7 cases regressed (b08, b12, b18, b20, b27, b28, b29, b30, mt04)。觸發 revert（d5d1a59 + fa62dc9，forward-fix c0149ff）。

## 5. Layer B — Agent prefilter dispatch prompt

- [x] 5.1 SYSTEM_PROMPT 加 "Episode Reference Resolution" 段（commit 0e38b16）。（隨 revert d74eecd 刪除）
- [x] 5.2 `search_within_episode` tool description 加優先語句。（隨 revert 刪除）
- [x] 5.3 跳過 unit test，靠 task 6.2 baseline 驗證 EP-ref dispatch 行為。

## 6. Layer B — Prod deploy + Baseline B + 達標判定

- [x] 6.1 commit 0e38b16 push、prod build RUNNING、`/health` 200 確認。
- [x] 6.2 chat baseline only-B → `backend/eval/results/baseline-step1-layerB-only-2026-05-28-chat.json`。
- [x] 6.3 diff → `backend/eval/results/diff-step1-layerB-only-vs-baseline-2026-05-28.md`。A vs B 對比省略（A 已 revert + 都退步無比較意義）。
- [x] 6.4 **Layer B 達標判定：FAIL** — chunk_recall_grouped 0.482 → 0.340 (-0.142, 比 A 更差) / factual 0.892 → 0.875 (近不變) / 6 cases regressed (b08, b18, b20, b23, b29, mt04)。亮點：b14 contradict_check 0→1.0 + factual 0.5→0.8（agent 抓到反差）+ b11/b09/mt01/b02 進步。觸發 revert（d74eecd）。

## 7. Case study + 路線決議 + gitleaks

- [x] 7.1 `docs/case-studies/retrieve-quality-step1-idf-and-prefilter-2026-05-28.md` 完成（Phase 1-3 全程紀錄 + Postmortem）。
- [x] 7.2 路線決議：兩 Layer 都失敗 → **不**開 `lexical-bm25-replace-ts_rank` 候選 C（也是 weighting 路線、同盲點）。下一步走**評估框架升級**（Ragas + span-level tracing + per-question tool trace 落地）— 在 retrieval 觀察工具升級前不再動 retrieval / prompt。
- [x] 7.3 gitleaks scan：每次 commit 都跑 `gitleaks protect --staged --no-banner --redact` ✅ no leaks。
