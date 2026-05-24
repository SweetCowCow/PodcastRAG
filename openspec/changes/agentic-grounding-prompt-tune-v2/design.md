## Context

### 為什麼是 v2

剛 archive 的 `agentic-prompt-grounding-and-ordinal-tool` change ship 後：

- LLM judge 對 `extended-multi-turn-40.json` 40 個 turn 跑出來：severe hallucination 9 筆 = **0.225**，mild 11 筆 = 0.275，加總 50% turn 有幻覺
- 對比 baseline（gate 設 ≤ 0.20）反而**變嚴重** — prompt rule 寫了但沒擋住
- 證據檔：`backend/eval/results/llm_judge_grounding_and_ordinal.json`
- 案例 b01：使用者問節目主題，agent 直接編造一個不存在的節目名稱與描述，正好踩到「6 類絕對不能編造」清單的第 1 類（show title）

### canonical 兩種幻覺要分開修

`openspec/LANGUAGE.md` 區分：

| 類型 | 觸發條件 | 修法 |
|------|---------|------|
| Hallucination from noise | tool 回了相關但不含答案的 chunk → LLM 推論編造 | prompt grounding 強化 |
| Pure hallucination | 完全沒呼 tool 或 tool 回空 → LLM 憑印象編 | retrieval coverage / tool surface |

上一個 change 只動了 prompt grounding 段就 ship，沒先看 9 個 severe case 屬於哪一種——所以對 noise-induced 可能有效、對 tool-call-empty 完全沒用。

### 評分視角校準

依記憶 `feedback_bakeoff_perspective_calibration.md`：本次評分視角 = **human end-user**（user 是直接讀 agent 回答的人），不是 AI delegate。Severe hallucination 對 human user = 失去信任，所以 gate 比 mild 嚴格。

## Goals / Non-Goals

**Goals：**

- 把 severe hallucination rate 從 0.225 拉回 ≤ **0.10**（比 baseline 0.20 再砍一半以上）
- mild hallucination 不惡化（≤ 0.275 維持）
- answer_quality_mean 不退步（≥ 0.5375 維持）
- 證據：跑同份 `extended-multi-turn-40.json` + 同 judge model（gpt-4o）+ 同 calibration setting，severe ≤ 0.10 才算修好
- 把「9 個 severe 案例 root cause 分佈」變成可重跑、可審查的人造物，下次再 regress 時直接重跑

**Non-Goals：**

- 不動 tool 實作（`list_episodes` 等剛 ship 的 tool 不重改）
- 不改 judge model、judge prompt、dataset、calibration set——baseline 對比要鎖死
- 不處理 ordinal carry（context_carry_hit_rate 維持 0.33 即可，不在本 change 的 gate）
- 不換 agent 用的 chat LLM 模型
- 不重寫整份 SYSTEM_PROMPT，只重排 + 動 grounding 段
- 不追 mild 降為 0；mild 是「部分編造但無誤導性」，本 change 只 gate severe
- 不擴 golden set（不加新題目壓測新規則）

## Decisions

### D1：先 diagnose 9 個 severe + 11 個 mild case 再決定動 prompt 哪一段

**選擇**：先寫 `classify_hallucination_root_cause.py` 跑分佈，再依分佈走分支。

**Why**：上一個 change 跳過 diagnose 直接套規則，severe 從 0.20 升到 0.225——證明「不對 root cause 就改 prompt」會 regress。canonical vocab 明說兩種幻覺修法不同。

**Alternatives**：
- 純人工眼看 9 個 severe case → reject：11 個 mild 也要看，20 筆 LLM 標一致性比眼看高
- 直接補 few-shot example 試試看 → reject：可能對 noise-induced 有效但對 tool-call-empty 無效，又回到「沒對到靶」的 regression 模式

### D2：Diagnose 用 LLM-as-classifier，不是 rule-based

**選擇**：用 gpt-4o 對每筆 turn 讀 `(query, tool_calls, tool_results, final_answer)` 後吐 `root_cause` 標籤，schema 固定 enum：

```json
{
  "item_id": "b01",
  "turn_index": 1,
  "severity": "severe",
  "root_cause": "tool_call_empty",
  "evidence": "tool_calls=[]，agent 直接回答節目名稱「也好吃」（不存在於資料庫）",
  "noise_chunk_ids": []
}
```

`root_cause` enum：
- `tool_call_empty`：`tool_calls` 為空 或 全 fail，agent 憑印象答
- `noise_induced`：tool 有回 chunk 但 chunk 不含答案，agent 從 chunk 推論編造
- `wrong_tool_chosen`：agent 呼了 tool 但 tool 名稱/參數錯，導致拿不到應該拿到的資料
- `tool_returned_partial`：tool 回了部分正確資料但 agent 把缺失欄位編造補上

**Why**：人工 20 筆判分容易主觀；LLM 用 fixed enum + evidence 欄位可重跑可審查。

**Alternatives**：
- Rule-based（看 `len(tool_calls) == 0` 直接標 empty）→ reject：分不出 noise_induced vs wrong_tool_chosen，兩者都呼了 tool

### D3：分支決策樹（threshold = 60%）

跑完 diagnose 後依分佈走：

| 主要 root cause | 修法 |
|----------------|------|
| `tool_call_empty` ≥ 60% of severe | **分支 A**：grounding rule 從第 5 段提前到第 2 段（在 tool-eager 之後立刻接），tool-eager 段補 negative example：「使用者問『這節目在講什麼？』時，**也要先呼 `find_show_by_name` 或 `list_episodes` 拿一集 description**，不要直接憑印象答」 |
| `noise_induced` ≥ 60% of severe | **分支 B**：grounding 段加 2 個 few-shot pair（譬如 q02 嘻哈冠軍 noise chunks → 編造答案 vs 「節目未提及嘻哈冠軍」拒答 template） |
| 混合（沒有單一 ≥ 60%） | **分支 A+B**：兩段都動，但避免重寫整份 prompt |

**Why**：60% 是「明顯主導」threshold；20% 落差以下難確定方向。

**Alternatives**：
- 一律 A+B 都做 → reject：違反「不對到靶就 regression」教訓，可能 prompt 變更長更稀釋
- threshold 50/50 split → reject：5/5 跟 6/4 修法不應該不同

### D4：Gate 標準 = severe ≤ 0.10 + 兩項守住

**選擇**：

- **必過**：severe hallucination rate ≤ 0.10（從 0.225 砍一半以上）
- **守住**：mild ≤ 0.275（不惡化）
- **守住**：answer_quality_mean ≥ 0.5375（不退步）

任何一條失敗 → 不 archive，回 design 重判分支或補 round 2。

**Why**：severe 0.10 是「比 baseline 0.20 明顯更好」+「為 chat agent 翻牌 day 3+ 守住信任」雙重門檻。

**Alternatives**：
- 鎖 severe = 0 → reject：規格初版這樣寫過但實際 unreachable，會卡死 archive
- 只鎖 severe，mild + quality 不管 → reject：可能用「全部拒答」這種爛策略壓 severe 但 quality 崩盤

### D5：跑 judge 用同 model（gpt-4o）+ 同 dataset，但留 calibration 證據

跑 v2 judge 時把 judge 的 `temperature` / `seed`（若 model 支援）/ prompt version 一起記到 result 檔 metadata，下次 regress 才有比對基準。

**Why**：上次 archive 時沒記 judge run env，無法事後 reproduce 0.225 結果。

## Implementation Contract

### 可觀察行為（ship 完後使用者 / operator 看到什麼）

1. **Diagnose script CLI**：

   ```bash
   python -m backend.eval.scripts.classify_hallucination_root_cause \
       --eval-file backend/eval/results/chat_eval_grounding_and_ordinal.json \
       --judge-file backend/eval/results/llm_judge_grounding_and_ordinal.json \
       --out backend/eval/results/hallucination_root_cause_distribution.json
   ```

   - 退出碼 0 = 跑完；非 0 = 有 turn 標不出來
   - stdout 印分佈表（severity × root_cause 交叉表）
   - 寫出檔含 `meta` (judge_model, dataset_file, run_at) + `turns` (per-turn 分類) + `summary` (分佈統計)

2. **修改後的 SYSTEM_PROMPT**：

   - 段落順序由 diagnose 結果決定（D3 分支）
   - 不改變既有「6 類絕對不能編造」清單內容（只動位置 + 補 few-shot）
   - 不改變 tool 錯誤處理規則、tool routing 分工段落

3. **Re-judge 結果**：

   - `backend/eval/results/chat_eval_grounding_v2.json`（agent 重跑）
   - `backend/eval/results/llm_judge_grounding_v2.json`（judge 重跑）
   - JSON `summary` 必須含 `hallucination_severe_count`、`hallucination_mild_count`、`answer_quality_mean` 對比 baseline

4. **Case study**：`docs/case-studies/agentic-grounding-prompt-tune-v2-2026-05-24.md` 至少含：
   - Diagnose 表（9 + 11 = 20 筆，每筆 item_id / severity / root_cause / evidence 一行）
   - 走的分支（A / B / A+B）+ 原因
   - 前後對比表（severe / mild / quality 三欄）
   - 若 gate fail，明寫卡在哪條 + 下一輪計畫

### Failure modes

- **Diagnose script 標不出 root cause**：LLM classifier 回傳 enum 外的值或 `null` → script exit 非 0，要求人工補標
- **重跑 judge 結果不穩**（同 prompt 跑兩次差 > 3 個 turn 的 severity）→ design 改：跑 3 次取多數決
- **Gate fail（severe > 0.10）**：archive blocked；回 design 評估是不是分支判斷錯、要不要 A+B 都做

### 驗收條件（reviewer 怎麼確認 contract 達成）

1. `hallucination_root_cause_distribution.json` 存在且 20 筆全有 root_cause 標籤（沒 null / unknown）
2. `prompts.py` git diff 只動 SYSTEM_PROMPT 字串，不動 import / 函式簽名
3. `llm_judge_grounding_v2.json` 的 `summary.hallucination_severe_count / 40 ≤ 0.10`
4. `llm_judge_grounding_v2.json` 的 `summary.hallucination_mild_count / 40 ≤ 0.275`
5. `llm_judge_grounding_v2.json` 的 `summary.answer_quality_mean ≥ 0.5375`
6. case study 三表齊全（diagnose / 分支選擇 / 前後對比）

### 範圍邊界

**In scope：**

- `backend/eval/scripts/classify_hallucination_root_cause.py`（新檔）
- `backend/app/services/chat_agent/prompts.py` 的 SYSTEM_PROMPT 字串（grounding 相關段落）
- Re-run `extended-multi-turn-40.json` agent eval + LLM judge
- Case study 文件

**Out of scope：**

- `backend/app/services/chat_agent/agent.py` 的 agent loop 邏輯
- `backend/app/services/chat_agent/tools.py` 的 tool 實作
- `backend/app/services/chat_agent/state.py` 的 ordinal carry
- judge prompt / judge model
- `extended-multi-turn-40.json` dataset
- Frontend / API endpoint

## Risks / Trade-offs

- **[Risk] LLM classifier 對「noise_induced vs wrong_tool_chosen」判錯** → Mitigation：每筆要求 evidence 欄位（具體 chunk_id 或 tool args），人工複核 20 筆只需 ~30 分鐘
- **[Risk] 分支 A 把 grounding 提前，可能稀釋 tool-eager 段的「先呼 tool 再決定」訊號** → Mitigation：D3 規定不動 tool-eager 段內容，只在它後面接 grounding，順序變但段不變
- **[Risk] severe 0.225 → 0.10 砍超過一半，可能 prompt 改動量不足以達成** → Mitigation：D4 gate fail 時走 round 2（A+B 都做 + few-shot pair 加倍），不直接 archive
- **[Risk] judge 本身 noise（跑兩次差很多）導致對比不穩** → Mitigation：failure mode 規定差 > 3 個 turn 就跑 3 次取多數決
- **[Risk] 分支判斷剛好卡在 50/50（兩種 root cause 各半）** → Mitigation：D3 已寫「沒有單一 ≥ 60% → A+B 都做」
- **[Trade-off] diagnose 用 LLM 比 rule-based 多花 ~$0.5 token 但換可重跑可審查** → 接受，未來 regress 時這份 script 直接 reuse
