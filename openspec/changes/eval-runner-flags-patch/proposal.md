## Why

`rag-eval-runner` skill v2.0（2026-05-10 升級）強制 6 個 discipline phase（preflight / canary / metric-sanity / variance / checkpoint / persistent runner）作為跑 full eval 前的 gate。但目前 `backend/eval/runners/run.py` 缺 4 個 phase 需要的 CLI flag，每次跑 full eval 都需要先手 patch runner，違反「skill 強制 gate」設計意圖。本 change 補齊這 4 個 flag，讓 skill 真的 callable。

## Why NOT defer

R2.1 archive 卡關事件（judge mean 0.71 → 0.50 跑了 3 輪 eval 都不知道是 noise 還 signal）的根因之一是「answer 沒持久化所以 prompt fix 都是結構推論」。下次任何 prompt / retrieval 改動都會撞同樣牆。skill 已寫好但 runner 沒 ready = 紙上談兵。

## What Changes

- `--canary N` flag：只跑 dataset 前 N 題就停（給 Phase 1 canary 用）
- `--persist-answers` flag：除了 score 還把 answer 全文 + retrieval_context 寫進每題 record（給 Phase 1 + RCA 用）
- `--checkpoint-every N` flag：每 N 題寫 partial result 到 `<out-dir>/.checkpoint.json`（給 Phase 4）
- `--resume <path>` flag：從 checkpoint 接續跑（給 Phase 4 crash recovery）
- 對應 unit test 確保 4 個 flag 行為正確

## Non-Goals

- 不改 metric / judge / dataset schema
- 不動現有 flag 行為（向後相容，新 flag 都是 opt-in）
- 不重構 runner 整體結構（只加 flag，不重新組織）
- 不做分散式 / 平行跑（單 process 即可）
- 不做 GUI / web dashboard（純 CLI）

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `rag-eval-runner`: CLI 加 4 個 flag 支援 canary mode / answer 持久化 / checkpoint resume

## Impact

- Affected specs: `rag-eval-runner`
- Affected code:
  - Modified:
    - `backend/eval/runners/run.py`（加 4 個 argparse flag + 對應 logic）
  - New:
    - `backend/tests/test_eval_runner_flags.py`
