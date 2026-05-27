## Context

2026-05-26 archive 的 `retrieval-cross-episode-episode-prefilter` 在 `chat-agentic-routing` 加了 `search_with_topic_prefilter` 這個新 tool（先找候選 episodes 再 retrieve_hybrid）。然而 `backend/app/services/chat.py` 內 `_collect_agentic_citations` 用一個 hard-coded whitelist `_AGENTIC_SEARCH_TOOLS` 來決定哪些 tool 的 result chunks 要被當成 citations 蒐集。新 tool 沒被加進 whitelist，結果 agent 走 prefilter 路徑時 `citations` 永遠空。

這個 latent bug 在 baseline + chunk-recovery + Voyage rerank 三個 change 的 eval 期間都存在。直到 `retrieval-rerank-via-voyage` 跑時 Voyage 把 prefilter 路徑自發採用率推高，bug 全面爆發、第一輪 eval 看起來「全 REGRESS、chunk_recall 全 0」才被發現，commit `287e73b` 修。

修完後重跑 Voyage 那輪得到「真實」對照（cross_episode mean 0.244→0.283），但這個 0.244 baseline 本身也在污染期。所以後續所有 retrieval-side change 的對照數據都需要洗。

**現狀 / 約束**：
- Prod backend 已部署 commit `336c69d`（含 citation fix `287e73b`）
- chat-rag dataset schema v2 已穩定在 `backend/eval/datasets/extended-multi-turn-40.json`
- runner `backend/eval/run_chat_agent_eval.py` 已支援 nested multi-turn + judge + per-design_type aggregate
- E2E session cookie 在 `~/.config/podcastrag/e2e-token`，prod URL `podcastrag-api.zeabur.app`
- Skill `rag-eval-runner` 提供 canary + preflight + checkpoint 紀律

## Goals / Non-Goals

### Goals
- 對 prod backend（含 citation fix）跑一次乾淨 chat-rag v2 全集 baseline
- 落盤 per-question 結果 JSON + design_type aggregate
- 產出舊（污染）vs 新（乾淨）per-question diff 表
- 在 case study 內標明：哪些已 archive 結論需要在 retrospective 加註「污染數據」
- 為 `voyage-rerank-tune-b22-b23` 提供 per-question 乾淨對照基準

### Non-Goals
- 不調 dataset、不改 grader、不重訓 judge
- 不對 cross_episode 退步題（b22/b23）做 root cause 分析（那是下一個 change 的事）
- 不跑 semantic / keyword 模式（citation bug 只影響 chat agent 路徑）
- 不重新 archive 之前的 changes
- 不動 production code

## Decisions

### 用 prod backend（含 `287e73b`）而非 local backend

**選**：對 prod backend 跑 baseline。
**因為**：
- `voyage-rerank-tune-b22-b23` 要對的就是 prod，baseline 必須跟它同樣境
- local 跑需另 sync embeddings / pgvector index / api keys，複雜度高且結果不可移植
- prod cost ~$1 可接受

**Alternative considered**：local backend dump → 若 prod 環境動盪改 dataset 時可重現。但 dataset 已凍結 v2，這個 alternative 沒急迫性。

### Baseline 落盤命名 + 路徑

**選**：`backend/eval/results/baseline-post-citation-fix-2026-05-27.json`（或實際執行日期）。
**因為**：
- `backend/eval/results/` 是 runner 預設輸出位置
- 檔名含「post-citation-fix」明確標示 vs 舊污染數據的對照
- 含日期方便未來再撈

### Per-question diff 表呈現方式

**選**：case study Markdown 表格，欄位 = `record_id` / `turn_index` / `question`（截 60 字） / design_type / 舊 chunk_recall / 新 chunk_recall / 舊 factual / 新 factual / Δ / 推測解讀。
**因為**：
- user 拍板「root cause 確認時要逐題列細節」（memory `feedback_root_cause_per_question_detail.md`）
- 表格便於 Voyage tune 那 change 直接引用對照
- 把 cross_episode 4 題單獨抽出來放放大鏡 section（因為 voyage tune 是針對這 4 題）

**Alternative considered**：CSV + Pandas DataFrame screenshot。可後續加，但 Markdown 表為主檔。

### 是否需要重跑 judge

**選**：不重跑 judge，本次只跑 runner（grader 部分）。
**因為**：
- citation bug 只影響 chunks 蒐集，不影響 LLM judge 對 answer 文字本身的評分
- 然而 `chunk_recall_grouped` grader 直接讀 citation chunks，必然受 bug 影響
- 重點 metric：`chunk_recall_grouped` / `citation_grounded`，這兩個非 judge metric

但若觀察到 answer 文字本身因 bug 在 agent prompt context 改變（agent 沒拿到 chunks → 答案降級），則 `answer_factual_correctness` 也會被影響。實務上要看新舊 answer 是否文字級別有差。

### Skill 紀律

**選**：用 `rag-eval-runner` skill 起跑（canary + preflight + checkpoint + persistent runner）。
**因為**：CLAUDE.md「Background Tasks」鐵律 — 長跑用持久化 runner、stdbuf -oL、PID 驗證。

## Implementation Contract

**可觀察的交付**：
1. 新 baseline JSON 落盤至 `backend/eval/results/baseline-post-citation-fix-<YYYY-MM-DD>.json`，欄位至少含 per-record results + design_type aggregate（與舊 baseline 同 schema）。
2. Case study `docs/case-studies/eval-baseline-citation-bug-revalidation-<YYYY-MM-DD>.md` 包含：
   - 污染期時間軸（commit hash + 影響範圍）
   - per-question diff 表（全 40 turn）
   - cross_episode 4 題放大鏡 section
   - design_type aggregate 對照表
   - 「已 archive change 結論需 revise 清單」
3. Memory update：`project_pending_changes.md` 標註「新 baseline = X」+「舊 0.244 已 deprecated」。

**驗證 done**：
- baseline JSON 檔存在、可被 `jq .aggregate.chunk_recall_grouped` 讀出非 null 數
- case study Markdown 含上述 4 個 section
- 至少 cross_episode 4 題的 per-question 數據呈現（query / GT episodes / 新 chunk_recall vs 舊 chunk_recall）
- 失敗模式：若 prod 跑回的 baseline 仍與舊 0.244 一致（chunk_recall 全 0 或極低），表示 prod 沒部署到 fix，需 abort + 重 deploy

**Scope in**：跑 chat 模式 baseline + per-question diff + case study。
**Scope out**：root cause 分析、code 變更、其他 metric mode。

## Risks / Trade-offs

- **[Risk] prod LLM 成本** — answer = gpt-4o 跑 40 turn 約 ~$1，可接受；但若 retry 多次成本可能堆。 → Mitigation：用 runner skill 的 checkpoint 模式，跑壞可從 checkpoint 續，不重跑已成功題。
- **[Risk] prod 環境動盪干擾 baseline** — embedding 表 / vector index 可能有別的 change 同時動。 → Mitigation：跑前先 admin smoke 確認 retrieval 對 b20 / b21 / b22 / b23 的 top-5 與 2026-05-27 Voyage 第二輪數據（commit `287e73b`）相同 chunks。
- **[Risk] 舊 baseline 找不到精確 per-question 數據** — 之前 archive 的 case study 可能只記 aggregate，diff 表會缺值。 → Mitigation：能撈到的就標，撈不到的用 `(舊資料 missing)` 標註；下次起 case study 都連 JSON 一起 commit（雖然 docs/case-studies/ 不入 git，但 backend/eval/results/ 入）。
- **[Trade-off] 不重 archive 之前 change** — case study 加註而非改 archive。 → 但 archive 是 immutable history，加註只能在新案例庫做交叉引用。

## Migration Plan

不適用（沒 prod code 改動）。執行步驟：

1. 確認 prod backend commit ≥ `287e73b`（zeabur deployment list）
2. Smoke：對 b20 跑一發 query，觀察 `citations` 非空
3. 啟 `rag-eval-runner` skill 跑全 40 turn baseline
4. 結果落盤 → diff 表撰寫 → case study
5. Memory 同步

**Rollback**：不適用，純讀取。若中途發現 prod 環境異常，abort 並等下次 prod stable。

## Open Questions

- 舊 baseline JSON 是否在 `backend/eval/results/` 找得到對應檔（不在 git tracked）？若找不到，per-question diff 只能跟 case study 內手抄表對比 — 接受這個 trade-off。
- 「污染期 archive changes 結論」標註要不要也同步進 `project_pending_changes.md` 的「最近 archive」表？傾向：是，但簡短一行「（含污染數據區間，詳見 case study）」。
