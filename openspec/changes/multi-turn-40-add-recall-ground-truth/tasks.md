## 1. 自動 copy 既有 chunk_id

- [ ] 1.0 實作 spec requirement「extended-multi-turn-40 dataset SHALL carry ground_truth_chunk_ids on scored turns」§ 自動 copy 14 turn 部分。
- [ ] 1.1 在 `backend/eval/scripts/copy_ground_truth.py` 新建 script：argparse 取 `--source backend/eval/datasets/this-not-that-cool.json` + `--target backend/eval/datasets/extended-multi-turn-40.json`；建立 source id → ground_truth_chunk_ids dict；遍歷 target items[].turns[]，凡 `source` 欄位以 `existing:` 開頭，取冒號後 id（譬如 `existing:q04-mid-age-opening-view` → `q04-mid-age-opening-view`），在 source dataset 找 `items[i].id` 對應、複製 `ground_truth_chunk_ids` 到 target turn。Dry-run mode (`--dry-run`) 印報告不寫檔。
- [ ] 1.2 跑 dry-run 確認預期 14 個 turn 會被 update；print 每個 turn id + 對應 source id + chunk_ids 長度。如果數字 < 14 或 > 14，先盤點 source 欄位再回頭調整 script 或補 mapping table。
- [ ] 1.3 跑正式 mode 寫入 dataset；驗證 `git diff backend/eval/datasets/extended-multi-turn-40.json` 只增 14 個 turn 的 `ground_truth_chunk_ids` 欄位 + 不動其他欄位。

## 2. 人工 audit 16 turn（覆蓋 extended-multi-turn-40 dataset SHALL carry ground_truth_chunk_ids on scored turns 第 2 部分）

- [ ] 2.1 列出 12 個 `source: "new"` 的 single-turn 題目（grep dataset `source.*new` + design_type != multi_turn）；存清單到 `/tmp/audit_new.txt`。
- [ ] 2.2 列出 4 組 multi-turn 第 1 turn 的題目（mt01 t1 / mt02 t1 / mt03 t1 / mt04 t1）；存清單到 `/tmp/audit_mt_t1.txt`。
- [ ] 2.3 對 16 個 turn 逐題人工 audit：搭配 prod 上的 search endpoint 或本機 transcripts table，找出 3-8 個 representative chunk_id（`ep:<episode_id>@<start_sec>` 形式）；填回 dataset 對應 turn 的 `ground_truth_chunk_ids` 欄位。每題 audit 過程記錄到 `docs/runbooks/eval-metrics-log.md`（或單獨檔）一行 audit note 方便未來複查。
- [ ] 2.4 寫一個 sanity check：跑 `python3 -c "import json; d=json.load(open('...extended-multi-turn-40.json')); turns=[t for it in d['items'] for t in it['turns']]; scored=[t for t in turns if t.get('ground_truth_chunk_ids')]; print(len(scored), len(turns))"`，confirm 至少 30 turn 有 ground truth。

## 3. multi-turn t2/t3 標 null（覆蓋 extended-multi-turn-40 dataset SHALL carry ground_truth_chunk_ids on scored turns 第 3 部分）

- [ ] 3.1 6 個 multi-turn 後續 turn（mt01 t2 / mt02 t2 / mt03 t2 t3 / mt04 t2 t3）顯式設 `ground_truth_chunk_ids: null`（不省略欄位，明確標示「intentionally skipped」）。
- [ ] 3.2 在每個 null turn 加 `ground_truth_note` 欄位 `"episode-level reference, chunk-level scoring not applicable"` 供未來 reviewer 理解。

## 4. dataset version + notes（covers extended-multi-turn-40 dataset SHALL carry ground_truth_chunk_ids on scored turns 第 4 部分）

- [ ] 4.1 dataset top-level `version` 從 `1` 改成 `2`。
- [ ] 4.2 `notes` 欄位 append：「v2 2026-05-XX: added ground_truth_chunk_ids on N scored turns (14 auto-copied from this-not-that-cool.json + 16 hand-audited); 6 multi-turn follow-up turns kept null (episode-level reference)」其中 N = 30。

## 5. Runner nested 路徑 Recall@5 啟用

- [ ] 5.0 實作 spec requirement「Nested-schema eval path SHALL compute Recall@K when turn carries ground_truth_chunk_ids」。
- [ ] 5.1 在 `backend/scripts/run_chat_agent_eval.py` 的 `_run_nested_eval` 內：每 turn 處理時，若 `turn_meta.get("ground_truth_chunk_ids")` 是 non-null list，先呼 `_search(backend_url, show_id, question, top_k, auth_token)` 取得 retrieved chunks，再用既有 `_recall_at_k(retrieved, gt, top_k)` 算分；無則設 `recall_at_k=None`。把結果填進 `turn_result["recall_at_k"]`。
- [ ] 5.2 aggregate 段改寫：`scored_recall = [t["recall_at_k"] for t in per_turn if t.get("recall_at_k") is not None]`；新增 `recall_at_k_mean = mean(scored_recall) if scored_recall else None` 跟 `n_scored_recall = len(scored_recall)`；其餘指標不動。
- [ ] 5.3 把舊的 `"recall_at_k_mean": None  # nested schema does not carry chunk ground truth` 寫死刪掉，改成新計算結果。

## 6. Test

- [ ] 6.1 新建 `backend/tests/test_eval_runner_nested_recall.py`：mock 一個 nested dataset 含 2 個 turn（一個有 ground_truth_chunk_ids、一個 null），mock `_search` 回固定 list；驗 aggregate `recall_at_k_mean` 是有 ground_truth 那條的 recall 值、`n_scored_recall=1`、null 那 turn 的 per-turn `recall_at_k is None`。
- [ ] 6.2 加 test case：dataset 全 null → aggregate `recall_at_k_mean is None` + `n_scored_recall == 0`，且 `answer_match_mean` 等其他指標仍正常 populate。
- [ ] 6.3 跑 `pytest backend/tests/test_eval_runner_nested_recall.py -v` 全綠。

## 7. 端到端驗證 + archive

- [ ] 7.1 用 backdoor session 對 prod 跑一輪 `run_chat_agent_eval.py --dataset extended-multi-turn-40 ...`，confirm 結果 JSON 的 `aggregate.recall_at_k_mean` 是 0-1 之間數字（非 null）+ `n_scored_recall ≥ 30`。
- [ ] 7.2 append 一行到 `docs/runbooks/eval-metrics-log.md`：標 dataset version=2、新增 Recall 欄位實測值。
- [ ] 7.3 commit + push（commit message 點明 dataset version bump + runner Recall 啟用 + 30 turn human-audited）。
- [ ] 7.4 `/spectra-archive multi-turn-40-add-recall-ground-truth`。
