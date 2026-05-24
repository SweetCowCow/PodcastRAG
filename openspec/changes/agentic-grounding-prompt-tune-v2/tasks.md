## 0. Spec & Design 對應

涵蓋以下 spec requirement 與 design decision，每個 task 後面括號標出對應編號：

- Spec requirement A：「System prompt instructs tool-eager grounded behaviour」（modified）→ task 3.x
- Spec requirement B：「Hallucination regression SHALL trigger root-cause classification before prompt modification」→ task 1.x
- Spec requirement C：「Hallucination gate for chat-agentic prompt changes」→ task 4.x + 5.x
- Design 為什麼是 v2 / canonical 兩種幻覺要分開修 / 評分視角校準 → task 1.x（diagnose 是 v2 的核心動作，分兩種幻覺 + human end-user 視角的依據）
- Design D1：先 diagnose 9 個 severe + 11 個 mild case 再決定動 prompt 哪一段 → task 1.x
- Design D2：diagnose 用 LLM-as-classifier，不是 rule-based → task 1.1 + 1.2
- Design D3：分支決策樹（threshold = 60%）→ task 2.x
- Design D4：gate 標準 = severe ≤ 0.10 + 兩項守住 → task 5.1
- Design D5：跑 judge 用同 model（gpt-4o）+ 同 dataset，但留 calibration 證據 → task 4.2
- Design 可觀察行為（ship 完後使用者 / operator 看到什麼）→ task 1.3 + 3.x + 4.x（CLI / prompt / re-judge 結果）
- Design failure modes → task 1.2 + 4.3 + 5.2（schema 驗 / judge 不穩三輪取多數 / gate fail 回 task 2）
- Design 驗收條件（reviewer 怎麼確認 contract 達成）→ task 6.1 + 6.2 + 6.3
- Design 範圍邊界 → task 6.1（驗 prompts.py diff 不溢出 SYSTEM_PROMPT）

## 1. Diagnose 9 severe + 11 mild case 的 root cause

實作 spec requirement「Hallucination regression SHALL trigger root-cause classification before prompt modification」（design D1 / D2）

- [x] 1.1 在 `backend/eval/scripts/classify_hallucination_root_cause.py` 寫 LLM classifier：讀 `chat_eval_grounding_and_ordinal.json` + `llm_judge_grounding_and_ordinal.json`，對每筆 severity ∈ {severe, mild} 的 turn 抽 `(query, tool_calls, tool_results, final_answer)` 給 gpt-4o 標 `root_cause` enum + `evidence` 一句話
- [x] 1.2 Script 加 schema 驗證：若 `root_cause` 為 null 或不在 4 個 enum 內，exit 非 0 且不覆寫已存在的分佈檔
- [x] 1.3 Script 輸出 `backend/eval/results/hallucination_root_cause_distribution.json`：包含 `meta` (judge_model, dataset_file, run_at)、`turns` (per-turn 分類)、`summary.severity_x_root_cause` 交叉表
- [x] 1.4 跑 script 對現有 9 severe + 11 mild 共 20 筆，stdout 印交叉表，人工抽 5 筆檢查 evidence 是否合理（不寫 code，只看）

## 2. 依分佈走分支判斷（design D3：分支決策樹 threshold = 60%）

- [x] 2.1 看 `summary.severity_x_root_cause` 算 severe 9 筆中 `tool_call_empty` / `noise_induced` 各佔比
- [x] 2.2 寫進 `docs/case-studies/agentic-grounding-prompt-tune-v2-2026-05-24.md` 的「分支決策」段：明寫主要 root cause、選哪個分支（A / B / A+B）、判斷依據（threshold 60%）

## 3. 修改 SYSTEM_PROMPT

實作 spec requirement「System prompt instructs tool-eager grounded behaviour」（依 task 2 分支執行）

- [x] 3.1 在 `backend/app/services/chat_agent/prompts.py` 的 SYSTEM_PROMPT 字串內，依分支調整：分支 A 把「事實 grounding 規則」段從第 4 段提前到第 3 段（緊跟 tool-eager 之後），且 tool-eager 段補一句「show overview / 節目主題類查詢也必須先呼 tool（譬如 `list_episodes` 拿一集 description）」
- [x] 3.2 分支 B（或 A+B）在 grounding 段內，原 6 類清單之後加入 2 個 few-shot example 區塊：(i) q02 嘻哈冠軍 noise → 編造 vs 拒答 對照、(ii) show overview 不存在節目 → 編造 vs 拒答 對照
- [x] 3.3 確認 prompt 五段結構名稱與既有 spec 段落順序契合：role → tool-eager → grounding（位置可能前移）→ tool-error → routing
- [x] 3.4 跑 `backend/tests/test_chat_agent_loop.py` 驗 prompt change 不破現有 unit test

## 4. Re-run agent eval + LLM judge（spec req C、design D5、failure modes：judge 不穩三輪取多數）

- [ ] 4.1 重跑 agent eval 對 prod backend、輸出 `backend/eval/results/chat_eval_grounding_v2.json`（dataset 鎖 `extended-multi-turn-40.json`）
- [ ] 4.2 跑 LLM judge 對上一步結果，輸出 `backend/eval/results/llm_judge_grounding_v2.json`（judge_model 鎖 `gpt-4o`），且 result `meta` 寫 judge_model + dataset_file + run_at
- [ ] 4.3 若同 prompt 跑兩次 severity 差 > 3 個 turn，再跑兩次共 3 輪取多數決，結果寫進 case study

## 5. 驗 gate + 寫 case study

實作 spec requirement「Hallucination gate for chat-agentic prompt changes」（design D4：gate 標準 + 評分視角校準）

- [ ] 5.1 對 `llm_judge_grounding_v2.json` summary 驗三項：`hallucination_severe_count / 40 ≤ 0.10`、`hallucination_mild_count / 40 ≤ 0.275`、`answer_quality_mean ≥ 0.5375`
- [ ] 5.2 若任一條 fail，回 task 2 重判分支或補 round 2（A+B 都做 + few-shot 加倍），不直接 archive
- [ ] 5.3 三條都過後，把前後對比表寫進 `docs/case-studies/agentic-grounding-prompt-tune-v2-2026-05-24.md`：欄位 severe / mild / quality / 走的分支 / 兩次 judge run 時間戳

## 6. Spectra archive 前置（design 驗收條件 + 範圍邊界）

- [ ] 6.1 驗 `prompts.py` git diff 只動 SYSTEM_PROMPT 字串，沒動 import / 函式簽名 / 其他常數
- [ ] 6.2 case study 含三表（diagnose 分佈 / 分支選擇理由 / 前後對比），補進 docs
- [ ] 6.3 跑 `spectra validate agentic-grounding-prompt-tune-v2` + `spectra analyze` 無 Critical / Warning
- [ ] 6.4 跑 `/spectra-archive agentic-grounding-prompt-tune-v2`
