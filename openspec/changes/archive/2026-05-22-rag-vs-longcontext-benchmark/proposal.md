## Status: SUPERSEDED (archived without implementation, 2026-05-22)

> 此 change 未走正式 propose → apply → archive 流程。2026-05-21 owner 直接用 spike 跑完整輪 4-arm benchmark（A long-context / B vanilla RAG / C rule-based / D agentic），結果寫成 case study `docs/case-studies/rag-vs-long-context-2026-05-22.md`（不入 git）並用 LLM judge 校驗 Arm D 領先（OVERALL 0.765）。本 change 內 19 條 tasks 全部由 spike 取代，archive 標記 superseded 收尾。下游 Phase 2 翻牌動作由 `enable-agentic-chat-default-on` change 接手。

## Why

2026-05-18 owner 跟另一個 AI 討論「context window 那麼大還需要 RAG 嗎」，整理出我們現行架構與「直餵 long context / 傳統 RAG / 混合路由」三種主流方案的對照。為了把直覺判斷升級為可驗證的數據結論，需要設計並執行一輪 benchmark：用我們特有的 podcast 場景（口語、跨集、ASR 錯字、時間戳、列舉題）真實比對三個 arm，產出 case study 後續可改寫為簡報。

## What Changes

- 真實執行 `docs/research/rag-vs-long-context-experiment-protocol.md` 全部步驟（前置基建 + 三 arm 搭建 + 30+ 題執行 + 評分 + case study 回填）
- 新增 `backend/eval/experiments/` 子目錄含 Arm A/B/C runner 與 driver
- 新增 vanilla RAG 服務 `backend/app/services/rag_vanilla.py`（純 chunk + top-k + LLM，關掉我們所有優化，當 baseline）
- 新增 chunking backfill script 寫 `transcript_chunks.chunking_version='vanilla'` row
- 新增 metric `bullet_coverage` + `timestamp_accuracy`
- 與 owner 共草 20 新題（補既有 `this-not-that-cool.json` 沒覆蓋的 G4 / G5 / G6 情境）
- 把實驗結果回填 `docs/case-studies/rag-vs-long-context-2026-05-XX.md`（10 個 [TBD] 替換為實測數據）

## Non-Goals (optional)

- 不重寫研究文 `docs/research/rag-vs-long-context-for-podcast.md`（已完成）
- 不重寫實驗 protocol `docs/research/rag-vs-long-context-experiment-protocol.md`（已完成）
- 不重做 case study 骨架 `docs/case-studies/rag-vs-long-context-2026-05-XX.md`（已完成）
- 不改我們現行 RAG 架構（純測量、不調整實作）
- 不把實驗 runner 列為 prod 必跑 CI 一部分（一次性研究用）
- 不評估 Anthropic / Gemini 模型（單純 OpenAI gpt-5-mini + AI Hub）
- 不把 vanilla RAG 服務開放給前端 user（純 backend benchmark 用）

## Capabilities

### New Capabilities

（無 — 純 research / 評估工作，不引入新 product 行為）

### Modified Capabilities

（無）

## Impact

- Affected specs: 無
- Affected code:
  - New:
    - `backend/eval/experiments/arm_a_longcontext.py`
    - `backend/eval/experiments/arm_b_vanilla_rag.py`
    - `backend/eval/experiments/arm_c_ours.py`
    - `backend/eval/experiments/run_all.py`
    - `backend/app/services/rag_vanilla.py`
    - `backend/scripts/build_vanilla_chunks.py`
    - `backend/eval/metrics/bullet_coverage.py`
    - `backend/eval/metrics/timestamp_accuracy.py`
    - `backend/eval/datasets/rag-vs-longcontext-questions.json`（與 owner 共草 20 新題，**不入 commit** per case-studies / research 規則延伸）
  - Modified:
    - `docs/case-studies/rag-vs-long-context-2026-05-XX.md`（10 個 [TBD] 替換成實測結果）
  - Removed: 無
- 既存資產（不入 commit、不重寫）：
  - `docs/research/rag-vs-long-context-for-podcast.md`（269 行，含 8 個 SLIDE marker）
  - `docs/research/rag-vs-long-context-experiment-protocol.md`（318 行，3 arm × G1-G6 × 預期矩陣）
  - `docs/case-studies/rag-vs-long-context-2026-05-XX.md`（227 行骨架）
- 預算：hard cap $10（per protocol 第 5.5 節），canary 階段單 arm > $1 即 abort
- 環境依賴：prod cookie `backend/eval/playwright-state.json`（apply 前需 owner 提供）、`OPENAI_API_KEY` 或 AI Hub key
- 不入 git：`docs/research/`、`docs/case-studies/`、`backend/eval/datasets/rag-vs-longcontext-questions.json`、`backend/eval/results/rag-vs-lc/`（per memory `feedback_case_studies_no_commit.md`）
