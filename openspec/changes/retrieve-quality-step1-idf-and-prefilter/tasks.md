## 1. Layer A — IDF infrastructure（migration + cache module）

- [ ] 1.1 落實 spec `IDF cache SHALL be refreshable via admin endpoint` 跟 design `Decision A1: IDF cache 走專屬 table、不走實時計算`：alembic migration 新增 `transcript_token_freq` table（PK = (show_id, token)，欄位 show_id uuid / token text / df bigint / total_docs bigint / idf double precision / updated_at timestamptz），含 INDEX on `(show_id)`。本地 Docker 沒開、跳本地驗證；prod 由 entrypoint.sh `alembic upgrade head` 觸發、用 `mcp__podcastrag-pg__query` `\d transcript_token_freq`-equivalent 驗 schema。
- [ ] 1.2 落實 design `Decision A1` 計算邏輯：新增 `backend/app/services/lexical_idf.py` module 含 `refresh_freq_table(db, show_id) -> dict` function — 對該 show 用 PG `ts_stat` over `transcript_chunks.text_tsvector` 統計 token document frequency（match retrieval-side 用的 lexicon），upsert 進 freq table，計算 `idf = ln((total_docs + 1) / (df + 1))`。回傳 `{tokens_written, total_docs, elapsed_ms}`。本地驗證跳過（無 Docker），prod 跑 admin endpoint 後驗 row count。
- [ ] 1.3 落實 design ``Decision A2: IDF 注入 ranking 走 multi-bucket `ts_rank` 加權和`` 的 helper：在 `lexical_idf.py` 新增 `get_idf_buckets(db, show_id, tokens: list[str]) -> dict[str, str]` — 對每個 token 查 freq table 拿 IDF、map 到 'A'/'B'/'C'/'D' bucket label（依 design 4-檔閾值：>8/5-8/2-5/≤2），缺值 fallback `C`。並新增 `build_bucketed_ts_queries(ts_query: str, buckets: dict[str, str]) -> dict[str, str | None]` — 把 `_build_ts_query` 產的 OR-join token string 依 bucket 重組成 `{"a": "tok1 | tok2" or None, "b": ..., "c": ..., "d": ...}`。本地驗證跳過（無 Docker）。
- [ ] 1.4 落實 design `Decision A4: IDF refresh 走 batch 不走 trigger`：新增 admin endpoint `POST /admin/lexical-idf/refresh?show_id=<uuid>` (或 `?all=true`) 觸發 `refresh_freq_table`。endpoint 走既有 admin auth gate、回 JSON `{status, tokens_written, elapsed_ms}`（per-show array if `all=true`）。本地驗證跳過（無 Docker），靠 prod admin curl 驗（task 3.1 一起做）。

## 2. Layer A — Lexical SQL 改 IDF weighting（rag.py）

- [ ] 2.1 落實 spec `Transcript lexical retrieval SHALL apply corpus-derived IDF weighting to token signals` 主路徑 + design ``Decision A2: IDF 注入 ranking 走 multi-bucket `ts_rank` 加權和`` + `Decision A3: 首版只動 transcript pool、不動 description / title`：修改 `backend/app/services/rag.py` 內 `_TRANSCRIPT_RRF_SQL` 把 lexical CTE 的 `ts_rank(...)` ORDER BY 換成 4 桶 `ts_rank` 加權和（A=1.0/B=0.5/C=0.2/D=0.05，CASE WHEN NULL 跳過）；retrieve() 加 IDF lookup + bucket split step（呼叫 `get_idf_buckets` + `build_bucketed_ts_queries` 拿 `:tsq_a/b/c/d` 四個 param）before SQL execute。match predicate `text_tsvector @@ to_tsquery('simple', :ts_query)` 保留不變、match count 不變；不動 `_DESC_RRF_SQL` 與 `_TITLE_LEXICAL_SQL`。本地驗證跳過（無 Docker），靠 prod DB probe 驗（task 3.2）。
- [ ] 2.2 落實 spec scenario「missing IDF entry falls back to neutral bucket」+「complete IDF table absence falls back to original ranking」failure modes：在 `retrieve()` 加 try/except 對 IDF lookup — 若 lookup 拋 exception，log warning + fallback 到舊版 `_TRANSCRIPT_RRF_SQL` SQL path（保留原 `ts_rank` 為 `_TRANSCRIPT_RRF_SQL_LEGACY` 常數）；若 lookup 回部分 token 缺值，缺值套 `C` bucket 後繼續走 bucketed path。本地驗證跳過（無 Docker），靠 prod smoke 驗。
- [ ] 2.3 跳過（合併到 3.2 prod DB probe）：spec scenario「high-IDF tokens rank earlier than low-IDF tokens」改用 prod DB probe 對 b14 query 驗證 — 罕見 token (`9543a933` GT 含的 entity) 對應 chunk 的 bucketed rank 是否高於只命中常見 token 的 chunk。

## 3. Layer A — Prod backfill + verify

- [ ] 3.1 落實 design Migration Plan Phase 1b（prod backfill）：commit + push migration + lexical_idf.py + endpoint 程式碼觸發 Zeabur build；redeploy 後對 prod 跑 `POST /admin/lexical-idf/refresh?all=true`（或對 3 個 active show 各跑一次），等回應 200。行為：prod `transcript_token_freq` table row count > 0。驗證：用 `mcp__podcastrag-pg__query` 跑 `SELECT show_id, COUNT(*) FROM transcript_token_freq GROUP BY show_id`、每 show row count > 5000。
- [ ] 3.2 落實 design Migration Plan Phase 1c（IDF SQL ship 後驗證）：對 b14 query 跑 prod DB probe — 計算 bucketed weighted sum rank（4 桶 ts_rank * weight），看 b14 GT chunks `9543a933` / `f6cd079f` 排名。驗證：兩 GT chunk 至少 1 個進 lexical pool top-50（vs RCA 紀錄的 #19K-32K）。同時驗 spec scenario「high-IDF rank earlier」— 罕見 token 對應 chunk rank 高於只命中常見 token 的 chunk。

## 4. Layer A — Baseline run（only A）

- [ ] 4.1 跑 chat 模式 baseline only Layer A：對 `extended-multi-turn-40.json` 跑 `backend/scripts/run_chat_agent_eval_v2.py`、落地 `backend/eval/results/baseline-step1-idf-only-2026-05-XX-chat.json`。驗證：result file 存在、含 chunk_recall_grouped / factual_correctness / hallucinated_cases 指標。
- [ ] 4.2 跑 `diff_baselines.py` 對比 step1-idf-only 跟 `baseline-post-judge-v2-2026-05-27.json`。驗證：diff 報告落地 `backend/eval/results/diff-step1-idf-only-vs-baseline-2026-05-XX.md`、列 per-question PASS→FAIL / chunk_recall delta。
- [ ] 4.3 Layer A 達標判定：chunk_recall_grouped 不退步（vs 0.482）+ factual_correctness 不退步（vs 0.892）+ 無 PASS→FAIL。若不達標 → revert commit + stop。驗證：判定寫進 case study Phase 1d 段。

## 5. Layer B — Agent prefilter dispatch prompt

- [ ] 5.1 落實 spec ``Chat agent SHALL dispatch explicit episode references to `find_episode_by_ref` first`` + design `Decision B1: EP-ref dispatch rule 走 prompt 不走 code branch`：在 chat agent SYSTEM_PROMPT（位於對應 prompt 檔或 `chat_agent.py` 內常數）加 "Episode Reference Resolution" 段，明寫三類 EP-ref pattern (`EP\d+` / `第\s*\d+\s*集` / 引號標記的 episode 標題) → 第一動 tool 必為 `find_episode_by_ref` + `search_within_episode`（或 summary-shape 用 `get_episode_summary`）。驗證：對應 prompt 檔 diff 含新增段落、本地 mock chat agent 對「EP134 ...」query unit test assert 第一 tool call = `find_episode_by_ref`。
- [ ] 5.2 落實 spec ``` `search_within_episode` tool description SHALL declare priority for episode-referenced queries ``` + design ``Decision B2: 同時補強 `search_within_episode` tool description``：在 `search_within_episode` tool schema description 加一句「whenever the user names a specific episode by number, EP-ref, or title, this is the FIRST choice — do NOT fall back to global search for these queries」。驗證：對應 schema definition 檔 diff 含新文字、本地 import tool schema 印 description 字串確認含該句。
- [ ] 5.3 跳過 unit test（無 Docker 跑 pytest）：spec scenario「EP-ref triggers episode-scoped dispatch」改用 eval baseline 驗 — b14 / mt03 t1 / mt04 t1 的 tool trace 應顯示第一 tool = `find_episode_by_ref`，併入 task 6.2 baseline 跑完一起 audit。

## 6. Layer B — Prod deploy + Baseline A+B + 達標判定

- [ ] 6.1 落實 design `Decision B3: A 跟 B 各自獨立 commit、分階段 verify` 第二階段：commit + push Layer B 程式碼（獨立於 Layer A commit）→ Zeabur build；redeploy。驗證：deployment list RUNNING + commit SHA 對齊 + `/healthz` 200；git log 顯示 A、B 各自獨立 commit 可單條 revert。
- [ ] 6.2 跑 chat 模式 baseline A+B：落地 `backend/eval/results/baseline-step1-idf-prefilter-2026-05-XX-chat.json`。驗證：result file 存在、metric 非 null。
- [ ] 6.3 跑 `diff_baselines.py` 對比 step1-idf-prefilter 跟 v2 baseline；另跑一份對比 step1-idf-only 跟 step1-idf-prefilter（拆 A 跟 B 各自貢獻）。驗證：兩份 diff 落地、per-question 表能讀出 b14/mt03 t1/mt04 t1 進步是 B 貢獻、b18/b20-style 是 A 貢獻（或相反）。
- [ ] 6.4 Success Criteria 全條判定：chunk_recall_grouped ≥ 0.55 / factual ≥ 0.88 / hallucinated=0 / 無 PASS→FAIL。判定結果 PASS / PARTIAL / FAIL 寫進 case study Phase 3 段。

## 7. Case study + 路線決議 + gitleaks

- [ ] 7.1 撰寫 `docs/case-studies/retrieve-quality-step1-idf-and-prefilter-2026-05-XX.md`：含 Background（連到 archived `lexical-stopword-filter-rca-deep-dive`）、Phase 1-3 全程紀錄、IDF table 規模 + backfill 時間、b14 prod DB probe 結果、A vs B per-question contribution 表、Success Criteria 判定。驗證：手動 review、所有段落齊全、單一 overall 達標結論。
- [ ] 7.2 依達標判定決定後續路線並寫進 case study 末段：全達標 → archive + 路線圖更新；部分達標 → propose `lexical-bm25-replace-ts_rank`（候選 C）；退步 → 看 commit 拆 A / B 單條 revert + 寫退步分析。驗證：case study 末段明確路線決議。
- [ ] 7.3 gitleaks scan：`gitleaks protect --staged --no-banner --redact` 對 staged 檔案跑 0 finding。驗證：command exit code 0、stdout `no leaks found`。
