## Why

剛 archive 的 `agentic-prompt-grounding-and-ordinal-tool` change 在 `SYSTEM_PROMPT` 加了「6 類絕對不能編造」清單，但 LLM judge 跑 `extended-multi-turn-40.json` 出來 severe hallucination 9/40 = 0.225，**比 baseline 0.20 還差**——規則寫了卻沒擋住，等於 prompt 改造 regression。

根因是上一個 change 同時塞 (A) tool surface + (B) ordinal verify + (C) hallucination prompt 三件事，scope 太雜時 hallucination 沒做 root cause 分佈就直接套 prompt rule。canonical vocab 區分兩種幻覺修法：noise-induced 修 prompt grounding、pure hallucination（無 retrieve 憑空編）修 retrieval coverage——**混在一起修就會像現在這樣，動了規則但沒對到靶**。

需要 v2 走「先 diagnose 9 個 severe + 11 個 mild case → 拿 root cause 分佈 → 對症動 prompt 或加 tool → 重跑 judge」三段式，把 severe rate 從 0.225 拉回 ≤ 0.10。

## What Changes

- **新增 diagnose script**：`backend/eval/scripts/classify_hallucination_root_cause.py`，對 `chat_eval_grounding_and_ordinal.json` 每筆 turn 標 `root_cause` ∈ `{tool_call_empty, noise_induced, wrong_tool_chosen, tool_returned_partial}`，輸出分佈表
- **修改 `SYSTEM_PROMPT`**：依 diagnose 結果走兩條分支之一
  - 若 `tool_call_empty` 為主：grounding rule 提前到第 2 段、tool-eager 段補「show overview / 角色介紹類也必須先呼 tool」negative example
  - 若 `noise_induced` 為主：grounding 段加 few-shot negative→positive pair（譬如 q02 嘻哈冠軍 noise chunk → 編造答案 vs 拒答 template）
- **新增 re-judge gate**：跑同份 `extended-multi-turn-40.json` + 同 judge model（gpt-4o），severe rate ≤ 0.10 才算修好
- **case study 更新**：`docs/case-studies/agentic-grounding-prompt-tune-v2-2026-05-24.md` 記 diagnose 表 + 分支決策 + 前後對比

## Non-Goals

- **不動 tool layer 實作**：上一個 change 剛加 `list_episodes` + `find_episodes_by_date_range` 的 `order/limit`，v2 純 prompt + diagnose，避免再混 scope
- **不改 judge model 或 dataset**：要跟 baseline 0.20 / regression 0.225 直接對比，judge prompt + dataset 必須鎖死
- **不處理 ordinal carry**：上一個 change 的 (B) 已 verify，v2 不重碰
- **不重寫整份 prompt**：只動 grounding 相關段落 + 必要重排，避免引入新 regression
- **不引入新 LLM 模型**：agent 仍走既有 chat model，避免 model swap 混淆 prompt 效果

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `chat-agentic-routing`：SYSTEM_PROMPT grounding 段重寫條款（順序 + few-shot），須改既有 requirement

## Impact

- Affected specs: `chat-agentic-routing`
- Affected code:
  - Modified: backend/app/services/chat_agent/prompts.py
  - New: backend/eval/scripts/classify_hallucination_root_cause.py
  - New: backend/eval/results/hallucination_root_cause_distribution.json
  - New: docs/case-studies/agentic-grounding-prompt-tune-v2-2026-05-24.md
