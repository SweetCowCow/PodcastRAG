## 1. Code implementation — stop-word set + filter logic

- [x] 1.1 落實 spec requirement「Lexical query builder SHALL filter stop-words from jieba token stream」+ design `Decision 1: Stop-word filter 採「黑名單常數」而非「IDF 動態計算」` + `Decision 2: Stop-word list 寫死在 code，不走 env 或 DB 配置`：在 `backend/app/services/rag.py` 模組頂部新增 `_STOP_WORDS: frozenset[str]`，內容涵蓋 design Decision 1 example 列出的中文虛詞 / 連接詞 / 疑問詞 / 高頻動詞 / 數量詞 / 英文 stop-word，預期 ~50-80 個 entry。行為：consumer 從 `rag` 模組可 import `_STOP_WORDS` 並 type 為 frozenset；不走 env、不走 DB，硬編在 code。驗證：本機 `python -c "from backend.app.services.rag import _STOP_WORDS; print(type(_STOP_WORDS).__name__, len(_STOP_WORDS))"` 印出 `frozenset` 跟 ≥50 的數字。
- [x] 1.2 落實 spec requirement「Lexical query builder SHALL drop single-character tokens」+ design `Decision 3: 1-char drop 補實作，作為 stop-word filter 的第二層防線` + `Decision 4: 兩條 filter 順序：stop-word filter 先、1-char drop 後`：修改 `_build_ts_query` 函式：在現有「過濾純標點」這層之後、show-name filter 之前，先加 `if tok in _STOP_WORDS: continue`，再加 `if len(tok) < 2: continue`（順序鎖定 stop-word 先、length 後）。行為：cleaned token list 不含任何 stop-word、不含 1-char token；其餘流程不變（OR 拼接、return None on empty）。驗證：本機跑 unit test（task 2.x）全綠。

## 2. Unit test coverage — `_build_ts_query` 行為驗證

- [x] 2.1 新增 `backend/tests/services/test_build_ts_query_filter.py` 並寫 `test_b20_query_token_count`：對 b20 query「迪拉胖在 EP134 為什麼不挑一首振奮的開工歌？他選的歌想表達什麼概念？」呼叫 `_build_ts_query`，assert 回傳字串切「 | 」後 token 數 ≤ 10、不含「的 / 不 / 什麼 / 在 / 為 / 一首」。驗證：pytest 跑此 case 綠燈。
- [x] 2.2 寫 `test_pure_stopword_query_returns_none`：對「為什麼？」呼叫 `_build_ts_query`，assert 回傳 `None`。驗證：pytest 綠燈。
- [x] 2.3 寫 `test_1char_cjk_dropped`：對「我去了那裡」（jieba 切出全 1-char 或 stop-word）呼叫 `_build_ts_query`，assert 回傳字串不含任何 length=1 的 CJK token，或回傳 `None`。驗證：pytest 綠燈。
- [x] 2.4 寫 `test_multichar_english_preserved`：對「RAG EP134 怎麼用？」呼叫 `_build_ts_query`，assert 回傳含 `RAG` 跟 `EP134`、不含「怎麼」「用」。驗證：pytest 綠燈。
- [x] 2.5 寫 `test_stop_words_set_immutable`：嘗試 `_STOP_WORDS.add("test")` assert 拋 `AttributeError`。驗證：pytest 綠燈。

## 3. Prod redeploy + DB probe 驗證

- [ ] 3.1 commit + push 觸發 Zeabur build。若 webhook 不穩用 `zeabur service redeploy --id 69eb10360da29f05f49a4b0b -y -i=false`。行為：prod backend 跑新 commit SHA。驗證：用 `Monitor + zeabur deployment list` pattern（per memory `feedback_zeabur_deploy_monitor_pattern.md`）等到 RUNNING + commit SHA 對齊新 commit；`/healthz` 回 200。
- [ ] 3.2 落實 spec requirement「Lexical pool size SHALL shrink to a tractable scale after filters apply」首條 scenario（b20 reference query lexical match count is bounded）：用 `mcp__podcastrag-pg__query` 對 b20 query 對應的新 ts_query（task 1.2 後的輸出，預期類似「迪拉胖 | EP134 | 挑 | 振奮 | 開工歌 | 他選 | 歌想表達 | 概念」）跑 `SELECT COUNT(*) FROM transcript_chunks c JOIN transcripts t ON ... JOIN episodes e ON ... WHERE e.show_id = '<百靈果 show_id>' AND c.text_tsvector @@ to_tsquery('simple', '<新 ts_query>')`。驗證：count 結果 < 1,000（vs baseline 39,323）。
- [ ] 3.3 落實 spec requirement「Lexical pool size SHALL shrink to a tractable scale after filters apply」第二條 scenario（ground-truth chunks enter lexical pool top 50）：對同一 ts_query 跑 `WITH ranked AS (SELECT c.id, ROW_NUMBER() OVER (ORDER BY ts_rank(c.text_tsvector, to_tsquery('simple', '<新 ts_query>')) DESC) AS rn FROM transcript_chunks c JOIN ... WHERE ... AND c.text_tsvector @@ to_tsquery(...)) SELECT * FROM ranked WHERE id IN ('9543a933-...', 'f6cd079f-...')`。驗證：兩 GT chunk 至少 1 個 rn ≤ 50。

## 4. 三模式 baseline eval + 達標判定

- [ ] 4.1 跑 chat 模式 baseline：對 `backend/eval/datasets/extended-multi-turn-40.json` 跑 `backend/eval/runner_v2_aggregate.py`，落地 `backend/eval/results/baseline-stopword-filter-2026-05-28-chat.json`。行為：chat 模式 baseline 含 chunk_recall_grouped / factual / hallucinated_cases / per-question grading。驗證：result file 存在、metric 欄位數值非 null。
- [ ] 4.2 跑 semantic 模式 baseline，落地 `backend/eval/results/baseline-stopword-filter-2026-05-28-semantic.json`。驗證：同 4.1。
- [ ] 4.3 跑 keyword 模式 baseline，落地 `backend/eval/results/baseline-stopword-filter-2026-05-28-keyword.json`。驗證：同 4.1。
- [ ] 4.4 跑 `backend/eval/scripts/diff_baselines.py` 對比三新檔 vs `backend/eval/results/baseline-post-judge-v2-2026-05-27.json`。行為：產出 per-question PASS→FAIL / FAIL→PASS 表 + per-metric delta。驗證：diff output 落地 case study 內 diff 段。
- [ ] 4.5 對三模式 baseline 套用 Success Criteria 全條判定（chunk_recall_grouped ≥ 0.55 / factual ≥ 0.88 / hallucinated=0 / 無 PASS→FAIL）。行為：每模式得 PASS / PARTIAL / FAIL 三選一。驗證：結果寫進 case study 達標判定段，每模式一個明確判定。

## 5. Case study + 路線決議

- [ ] 5.1 撰寫 `docs/case-studies/retrieve-hybrid-lexical-stopword-filter-2026-05-28.md`：含 Background（引 archived RCA + 訂正段）、root cause 確認（prod DB probe 從 39K 降到 < 1K + GT rank 進 top-50）、Phase 1a-1g 全程紀錄、stop-word list v1 內容附錄、三模式 diff 表、Success Criteria 達標判定、follow-up 建議。行為：case study 是 archive 前最後 audit 證據。驗證：手動 review case study 全段、確認所有段落存在、命名單一 overall 達標結論（pass / partial / fail）。
- [ ] 5.2 依達標判定決定後續路線並寫進 case study 末段：全達標 → Phase 2/3 暫不動；部分達標 → 提案 `retrieve-hybrid-per-side-widen` 或 R4 `retrieve-hybrid-noise-flood-safety-net`；退步 → 列 revert plan 與 root cause 假設。行為：case study 末段明確指引下一個 change 名稱與啟動條件。驗證：手動 review 末段、確認有明確路線決議。
- [ ] 5.3 gitleaks scan：`gitleaks protect --staged --no-banner --redact` 對 staged 檔案跑 0 finding。行為：code diff 不洩 secret。驗證：command exit code 0、stdout 顯示 no leaks。
