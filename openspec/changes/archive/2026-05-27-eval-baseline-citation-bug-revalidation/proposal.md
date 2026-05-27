## Why

2026-05-26 ~ 2026-05-27 期間 `_AGENTIC_SEARCH_TOOLS` whitelist 漏掉了新加的 `search_with_topic_prefilter` tool，導致 `_collect_agentic_citations` 在 agent 採用 prefilter 路徑時把 chunks 清空。這個 latent bug 在 `retrieval-rerank-via-voyage` 跑 eval 時才暴露（commit `287e73b` 修復）。

結果：所有以「cross_episode chunk_recall 0.244 baseline」為對照基準的結論都被污染，包含 `retrieval-cross-episode-chunk-recovery` 的「持平」negative finding、`retrieval-cross-episode-episode-prefilter` 的「mean 持平」結論、以及 `retrieval-rerank-via-voyage` 的第一輪 regress 數據。

下一個 change（`voyage-rerank-tune-b22-b23` diagnostic-first stage）需要乾淨的 per-question baseline 才能正確歸因 b22/b23 退步是 Voyage rerank 本身的問題還是 baseline 數字本來就不對。

這次事件也暴露 `rag-eval-runner` 目前缺少明文的「baseline provenance」契約：baseline 檔沒被要求記錄 prod backend commit hash、citation collector 狀態、執行日期。這個缺口讓污染期數據沒有 audit trail。

## What Changes

- 在 prod backend（commit ≥ `287e73b` 已含 citation collector fix）對 chat-rag dataset schema v2（`extended-multi-turn-40.json`）全 34 record / 40 turn 重跑一次 baseline eval。
- 產出新 baseline JSON 落盤至 `backend/eval/results/baseline-post-citation-fix-<YYYY-MM-DD>.json`，含 prod commit hash + 執行日期 + dataset version 等 provenance metadata。
- 依 design_type 分組計算 aggregate 指標（chunk_recall_grouped / factual / refusal_appropriateness / answer_match / citation_grounded）。
- 產出 per-question diff table：舊（污染）baseline vs 新（乾淨）baseline 每題逐項對照，標明哪些題目結論需要 revise。
- 撰寫 case study `docs/case-studies/eval-baseline-citation-bug-revalidation-<YYYY-MM-DD>.md`，列出污染區間、影響範圍、修正後的真實基準。
- 補 `rag-eval-runner` spec：baseline result file SHALL 含 provenance metadata（解決上述契約缺口）。
- 不修改 production code、不擴 dataset 內容。

## Non-Goals (optional)

- 不重啟 multi-turn ordinal mechanical resolution 等其他 follow-up change。
- 不調 dataset 內容、grader plugin、judge prompt（v2 已穩定）。
- 不重新 archive 之前已 archive 的 changes（只在 case study 標註）。
- 不跑 semantic / keyword 模式 eval（只 chat 模式，這是 citation bug 影響的範圍）。
- 不對 b22 / b23 退步題做 root cause（屬下個 change）。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `rag-eval-runner`: 加 baseline provenance 要求 — runner 落盤的 baseline JSON 須含執行時 prod backend commit hash、dataset version、執行日期、citation_collector_fix_applied bool 等 audit metadata。

## Impact

- Affected specs: `rag-eval-runner`（ADDED Requirement: baseline result provenance metadata）
- Affected code:
  - New:
    - backend/eval/results/baseline-post-citation-fix-<YYYY-MM-DD>.json
    - docs/case-studies/eval-baseline-citation-bug-revalidation-<YYYY-MM-DD>.md
  - Modified:
    - backend/eval/run_chat_agent_eval.py（落盤時寫入 provenance metadata 區塊）
  - Removed: 無
- Affected ops:
  - Prod backend smoke 確認 commit `287e73b` 已部署
  - 跑全集 40 turn baseline，預估 prod LLM 成本 ~$1
- 後續 unblock：`voyage-rerank-tune-b22-b23` diagnostic-first 可拿乾淨 per-question 數據對比 Voyage arm。
