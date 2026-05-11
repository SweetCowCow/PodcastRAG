## 1. CLI flags

- [x] 1.1 在 `backend/eval/runners/run.py` 的 argparse 加 Canary mode (--canary N)（int, default None）+ validation N > 0
- [x] 1.2 加 Answer persistence (--persist-answers) flag（store_true, default False）
- [x] 1.3 加 Checkpointing (--checkpoint-every N + --resume)（int default 0、str default None）
- [x] 1.4 互斥檢查：`--canary` 跟 `--resume` 互斥（resume 限定 full run）

## 2. Logic

- [x] 2.1 dataset iteration loop 開頭 `if args.canary: items = items[:args.canary]`
- [x] 2.2 per-item record 條件含 answer / retrieved_texts / retrieval_context_for_judge：if args.persist_answers
- [x] 2.3 checkpoint write helper：每 N items 完成寫 `<out-dir>/.checkpoint.json`（atomic：先寫 tmp 再 rename）；正常結束刪除
- [x] 2.4 resume helper：load checkpoint、validate dataset path 一致、跳過已 processed item ids、合併最終報告
- [x] 2.5 output filename 加 `.canary` 後綴 if canary mode

## 3. Tests

- [x] 3.1 寫 `backend/tests/test_eval_runner_flags.py`：
  - test_canary_3_processes_only_first_3
  - test_canary_zero_rejected
  - test_canary_omitted_runs_full
  - test_persist_answers_includes_extra_fields
  - test_persist_answers_default_lean_output
  - test_checkpoint_written_every_n
  - test_checkpoint_deleted_on_success
  - test_resume_skips_processed
  - test_resume_mismatched_dataset_rejects
  - test_back_compat_no_flags_unchanged
- [x] 3.2 跑 `pytest backend/tests/test_eval_runner_flags.py -v` 全綠

## 4. Docs + 收尾

- [x] 4.1 更新 `.claude/skills/rag-eval-runner/SKILL.md` 把「runner 必須支援」hint 移除（v2.0 文件中提到「沒這 flag 先 patch」段）
- [x] 4.2 釋出筆記寫進 release log v1.x（user 視角：「eval 工具現在能 canary 試跑 + 跑到一半當機可從中斷處接續」）
- [x] 4.3 commit + push（不需要 deploy prod，runner 是 local CLI）
