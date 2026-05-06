## Why

R1 評測框架第二塊（per `docs/research/r1-rag-eval-brief.md` 2026-05-05 議程結論；R1.1 已 archive 在 `2026-05-05-r1-ui-feedback-infra/`）。沒有評測框架，後續 Phase B / C 的 RAG 改動（R3 混合檢索 / R2 答案 prompt 強化 / R4 cache）改一改不知道是變好還變壞。本 change 把「自動跑全套指標 → 輸出 JSON 報告」的骨架建好，並產出第一個節目（這又沒有很屌）的 50 題 golden set，同時封裝成 skill 讓未來新節目上架可半自動產 golden set。

## What Changes

- **Judge model bake-off**：對 4 個候選（gpt-5-nano / gemini-2.5-flash-lite / gpt-4o-mini / claude-haiku-4-5，全走 Zeabur AI Hub）跑 20 題人工標分 mini-set，計算與人工分數的 Spearman 相關係數，> 0.7 才晉級；從晉級候選中挑最便宜的當 production judge，gpt-4o 留 quarterly cross-check。流程腳本化成 `backend/eval/scripts/judge_bakeoff.py`，未來新增候選可一鍵重跑。
- **Golden set v1（節目：這又沒有很屌）**：50 題（10 sentinel 手作 + 40 core 70% 合成 30% 抽審）。題型分佈：事實 19 / 理解 12 / 跨集 10 / 否定 6 / code-switch 3。每題標 ground-truth chunk_ids（用 LLM 反向找候選 + 人工抽審），存成 `backend/eval/datasets/this-not-that-cool.json`。
- **Eval framework 骨架**（`backend/eval/`）：
  - 自寫 Recall@5 / MRR（純 numpy，~30 行）
  - DeepEval pytest 跑 Faithfulness + AnswerRelevancy（用 production judge）
  - `backend/eval/run.py` 一鍵跑全套：load dataset → 呼叫 `/query` API → 算 4 個指標 → 輸出 JSON 到 `backend/eval/results/{date}-{show_slug}.json`
  - per-show + overall 兩種切片
  - 加 backend dependency：`deepeval`
- **CI workflow**：`.github/workflows/eval.yml` 在 main 上 nightly 跑 + manual `workflow_dispatch`，結果寫 GitHub artifact，失敗不 block PR
- **Golden Set Builder skill**：`.claude/skills/golden-set-builder/SKILL.md`，接 show_id + N=50（預設）+ 模式（v1 全建 / incremental 補 10 題），半自動跑「sample chunks → LLM 合成題目 → 標 ground-truth → 抽審 → 寫 JSON」流程，未來新節目上架直接用
- **路線 B 月底提醒**：Celery beat 每月 1 號掃 episodes 表，若節目「上次 golden set update > 30 天 + 期間新增 ≥ 10 集」→ ZSend 寄信給 admin；新增 `GET /admin/golden-set-status` admin-only endpoint 顯示每節目題數 / 上次更新日 / 是否需要補

## Non-Goals

- 不接 Langfuse trace（屬 R1.3）
- 不做 admin Dashboard 圖表化（Recall@5 / Faithfulness 趨勢視覺化屬 R1.3 polish）
- 不為其他兩節目（曼報 / 壹加壹電台）建 golden set — 本次先把流程跑通 + skill 蓋好，未來透過 skill 半自動產
- 不讀 R1.1 的 qa_feedback 表灌 sentinel（屬 R1.3，那時已累積 thumbs-down 真實案例）
- 不在 CI 上跑真 LLM judge（成本考量；nightly 跑 dev judge，main commit 只跑 Recall/MRR 不跑 judge）
- 不做 Recall@5 / Faithfulness 的 alerting（threshold 警報屬 R1.3）

## Capabilities

### New Capabilities

- `rag-eval-dataset`：golden set 資料模型（題目 / 題型 / ground_truth / sentinel flag）與檔案位置慣例
- `rag-eval-runner`：跑全套指標的 runner、輸出 JSON 報告格式、per-show + overall 切片
- `rag-eval-judge`：judge model 評選流程（bake-off）+ production judge 設定
- `golden-set-maintenance`：路線 B 月底提醒任務 + admin status endpoint

### Modified Capabilities

(none)

## Impact

- Affected specs: rag-eval-dataset (new), rag-eval-runner (new), rag-eval-judge (new), golden-set-maintenance (new)
- Affected code:
  - New:
    - backend/eval/__init__.py
    - backend/eval/datasets/this-not-that-cool.json
    - backend/eval/datasets/_schema.json
    - backend/eval/metrics/recall.py
    - backend/eval/metrics/mrr.py
    - backend/eval/metrics/__init__.py
    - backend/eval/runners/eval_runner.py
    - backend/eval/runners/__init__.py
    - backend/eval/scripts/judge_bakeoff.py
    - backend/eval/scripts/build_golden_set.py
    - backend/eval/run.py
    - backend/eval/judge_config.py
    - backend/eval/results/.gitkeep
    - backend/tests/test_eval_metrics.py
    - backend/tests/test_eval_runner.py
    - backend/app/api/admin/golden_set_status.py
    - backend/app/schemas/golden_set_status.py
    - backend/app/workers/golden_set_reminder.py
    - backend/tests/test_golden_set_reminder.py
    - .github/workflows/eval.yml
    - .claude/skills/golden-set-builder/SKILL.md
    - .claude/skills/golden-set-builder/README.md
  - Modified:
    - backend/requirements.txt
    - backend/app/workers/celery_app.py
    - backend/app/main.py
    - backend/app/api/admin/__init__.py
