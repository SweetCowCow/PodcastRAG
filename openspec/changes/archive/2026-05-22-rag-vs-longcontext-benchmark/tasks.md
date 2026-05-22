## 1. 前置：與 owner 共草 20 新題

- [ ] 1.1 與 owner 一題一題共草（不准 batch、不准 LLM 自動產），題目分組 G4 timestamp（5）/ G5 ASR 錯字（5）/ G6 speaker 區分（5）/ G2-G3 補強（5），寫到 `backend/eval/datasets/rag-vs-longcontext-questions.json`（不入 commit）。完成標準：JSON 含 20 個 object、每個 object 有 `id` / `group` / `question` / `expected_answer` / `expected_episodes`（list）/ `judging_notes` 六欄；owner 對每題 type / 考驗什麼 / 判斷標準三點明確同意

## 2. 前置：基建（vanilla service + chunking backfill + metrics）

- [ ] 2.1 新建 `backend/app/services/rag_vanilla.py`：純 chunk top-k + LLM，**關掉**所有優化（無 entity extraction / 無 paragraph aggregation / 無 ASR 校正 / 無 episode summary / 無 mode routing），輸出 `{answer, retrieved_chunks, cost_usd, latency_ms}`。完成標準：`python -c "from app.services.rag_vanilla import query; print(query.__doc__)"` 不 import error；single canary query 回傳結構正確
- [ ] 2.2 [P] 新建 `backend/scripts/build_vanilla_chunks.py`：fixed 512-token chunks 無重疊、寫 `transcript_chunks` 表 row 標 `chunking_version='vanilla'`、不動既有 `chunking_version='ours'` row。完成標準：clean run 後 `SELECT chunking_version, count(*) FROM transcript_chunks GROUP BY chunking_version` 看到 vanilla / ours 兩種版本、vanilla count 接近 ours 的 60-70%（chunk 較大故 row 較少）
- [ ] 2.3 [P] 新建 `backend/eval/metrics/bullet_coverage.py`：給定 `expected_bullets` list 與 `actual_answer` text，回 `{coverage: float (0-1), missing: list}`（用 LLM-as-judge 比對每個 bullet 是否被 cover）。完成標準：`pytest backend/tests/eval/test_bullet_coverage.py` 通過至少 2 個 case（全 cover / 半 cover）
- [ ] 2.4 [P] 新建 `backend/eval/metrics/timestamp_accuracy.py`：給定 `expected_timestamps` list（episode_id + seconds）與 `actual_citations` list，計算 IoU + 5 秒容差內命中率。完成標準：`pytest backend/tests/eval/test_timestamp_accuracy.py` 通過至少 2 個 case（完全命中 / 漂 10 秒）

## 3. 三個 Arm runner

- [ ] 3.1 新建 `backend/eval/experiments/arm_a_longcontext.py`：給 episode_ids list 直接 dump 全文 → LLM。完成標準：對 1 題 canary 跑成功、output JSON 含 cost/latency/answer/source_episodes
- [ ] 3.2 [P] 新建 `backend/eval/experiments/arm_b_vanilla_rag.py`：呼叫 `rag_vanilla.query()` 過濾 `chunking_version='vanilla'`。完成標準：對 1 題 canary 跑成功、retrieved_chunks 全屬 vanilla version
- [ ] 3.3 [P] 新建 `backend/eval/experiments/arm_c_ours.py`：透過 prod `/api/query` endpoint 呼叫（用 `playwright-state` cookie）。完成標準：1 題 canary 回傳含 mode/citations/answer
- [ ] 3.4 新建 `backend/eval/experiments/run_all.py`：driver 跑全 50 題（30 既有 + 20 新題）× 3 arm × 3 輪，checkpoint 進 `backend/eval/results/rag-vs-lc/<arm>/<question_id>__r<run>.json`，每 arm 預算 >$3 abort。完成標準：dry-run 模式（`--dry-run`）能印出將要跑的 question count、arm count、estimated cost 不執行 LLM

## 4. Canary + 正式跑

- [ ] 4.1 每 arm 先打 1 題 canary（建議用 G1 第 1 題）、確認 output shape + cost < $0.1，三 arm 全綠才繼續。完成標準：三個 canary JSON 落盤、owner 目視確認
- [ ] 4.2 nohup 啟動 `run_all.py` 跑三 arm × 3 輪、PID 寫 `/tmp/rag-exp-<arm>.pid`、log 寫 `/tmp/rag-exp-<arm>.log`（`python -u` 避免 buffering）。完成標準：三個 PID 都活著、log 有持續輸出、checkpoint 檔案數隨時間增長
- [ ] 4.3 監控：每 30 分鐘檢查 progress，總成本超 $7 ($10 hard cap 留 buffer) 立刻 abort。完成標準：完成或 abort 後 owner 收到摘要

## 5. 評分

- [ ] 5.1 跑 `rag-eval-judge` 對三 arm 的 raw output 打分（G1/G2/G3/G5 用 LLM judge）。完成標準：scores JSON 落 `backend/eval/results/rag-vs-lc/judge/`
- [ ] 5.2 跑 `timestamp_accuracy.py` 對 G4 題目自動算（不用人工）。完成標準：G4 IoU + 5s 容差數字寫 scores.csv
- [ ] 5.3 G6 speaker 區分**人工 review**：owner 看三 arm 對 G6 五題的 answer 判斷誰對。完成標準：G6 五題每題三 arm 各有 owner 給分 1-5

## 6. case study 回填

- [ ] 6.1 把 `docs/case-studies/rag-vs-long-context-2026-05-XX.md` 內 10 個 `[TBD:` 全部替換為實測數據（TL;DR / G1-G6 各組 / 整體表 / 預期 vs 實際 diff / 結論）。完成標準：`grep -c '\[TBD' docs/case-studies/rag-vs-long-context-*.md` == 0；檔名日期 XX 改成實際完成日
- [ ] 6.2 把實驗總成本、預測命中率（n/18）、最反直覺發現寫進 TL;DR 區（簡報用第一頁）。完成標準：TL;DR 段有三段、每段 ≤ 3 句

## 7. 結束

- [ ] 7.1 寫 `docs/research/rag-vs-long-context-followups.md` 列出實驗發現的後續工作（哪些假設被推翻、哪些 spec 要改、哪些新 change 要開）。完成標準：檔案存在、至少含 3 條 actionable follow-up
- [ ] 7.2 Memory 更新：在 `project_pending_changes.md` 把這個 change 從 pending 移除；新增 case study 連結到 reference memory
