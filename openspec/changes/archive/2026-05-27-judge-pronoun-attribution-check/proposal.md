## Problem

LLM judge（在 2026-05-26 `eval-judge-incorporate-tool-grounding` archive 時 ship）對 chat agent 答案做 factual_correctness 評分時，**有兩個物理層 + 邏輯層的雙重盲點**：

1. **物理層盲點**：judge input 只送 `result_summary`（`backend/app/services/chat_agent/agent.py:425` 把 tool result truncate 到 500 chars 然後當 summary 傳），**不送 `result_full`**。Judge 看不到 chunk 原文，物理上無法檢查代詞「他/她/我」的指向。
2. **邏輯層盲點**：現行 prompt rubric（`backend/eval/prompts/chat_judge_v2.md` factual_correctness section）只比對「答案 vs 期望 summary 的表面用詞」，沒有任何驗證「答案內提到的人物 = chunk 內代詞真實指向」的步驟。

具體 b23 案例（2026-05-27 user 親自聽逐字稿 audit 確認）：
- Query：「迪拉跟 Leo 王怎麼從不認識變成合作夥伴？」
- Agent 撈到 EP129 chunk @261.20「他說觀眾席裡就兩個人 一個是他一個是國蛋」 — chunk 內「他」實際指**呂安**（茉莉書房漫畫播客主持人），跟 Leo 王完全無關
- Agent 答：「Leo 王...觀眾席兩人是他和國蛋」— **代詞錯誤套用**，把呂安故事整段移植成 Leo 王故事
- 現行 judge 給 **factual_correctness = 0.95 過 gate**，完全沒抓到 hallucination

這個盲點影響所有「跨人物多代詞」的 chat-rag 評分結果可信度。

## Root Cause

兩層獨立根因：

1. **judge_chat_v2.py 在組 judge input payload 時**，遍歷 ChatAgentResult 的 tool_calls，只取 `result_summary`（前 500 chars 截斷版）寫進 prompt JSON，不取 `result_full`（含完整 chunk text + 上下文 overlap segment）。這個截斷在 `_build_payload` 或對等組 input 函式內。設計初衷是 token 節省，但代價是 judge 物理上看不到代詞 anchor。

2. **chat_judge_v2.md prompt 沒有 pronoun-attribution rubric**。現行三個 top-level keys (`factual_correctness` / `refusal_appropriateness` / `answer_contradict_check`) 都不涵蓋代詞驗證。即使 judge 看完整 chunk，也沒被引導去做這層檢查。

## Proposed Solution

四點，照 discuss 拍版方案執行：

**(1) 加新指標 `pronoun_attribution_check`，三類 verdict**
- 第 4 個 top-level JSON key，跟 `answer_contradict_check` 對稱（條件式 — 只當 expected 涉及多人關係時跑）
- 三態枚舉：
  - `grounded` — chunk 內直接寫人名 + answer 用同個人名
  - `inferred` — chunk 用代詞但有明確 anchor（前後句指向該人），answer 補名字是合理推理
  - `hallucinated` — chunk 用代詞但代詞指向別人 / 或 chunk 內沒任何 anchor 支持 answer 用的名字
- 不打信心分（boolean / score 都不要）— LLM judge 對 confidence calibration 通常不可信
- 對齊現有 `refusal_appropriateness` 的三態 pattern

**(2) 物理層：judge_chat_v2.py 餵 result_full 給 judge**
- 修改 judge input 組裝邏輯：tool_calls 內每個 tool 改傳 `result_full`（含 chunk text + overlap context）
- 保留 `result_summary` 在 envelope（為 admin debug trace 用），純擴 judge 看的內容
- token 成本評估：每個 tool result 從 500 chars 變 ~8000 chars (per `agentic_tool_result_max_chars`)，judge prompt 變約 16× 大。但 judge 模型 (gemini-2.5-flash-lite 或 gpt-4o-mini) context window 充足，cost 仍可控（~$1.5 全 40 turn vs 舊 ~$1）

**(3) Prompt 層：rubric section + b23 為 Example 4**
- chat_judge_v2.md 加新 rubric section「Pronoun attribution verification」：
  - 明確步驟「找出 answer 提到的具體人名 → 在 tool_calls result_full chunks 內定位該人名是否直接出現 / 推測代詞指向 / 沒有 anchor」
  - 三類 verdict 判定準則
- 加 b23 為 Example 4（hallucinated case）— 含完整 chunk text + agent answer + 正確判定
- 只加 1 個 example（per memory `feedback_prompt_saturation_more_is_less.md` 警告「加更多 example 反而 regress」）

**(4) 全集 34 record / 40 turn baseline 重算 + 落新檔**
- 用 `python -m backend.scripts.run_chat_agent_eval_v2 --output backend/eval/results/baseline-post-judge-v2-<DATE>.json --report ...`
- provenance metadata 內 `judge_prompt_sha256` 自然會變動（chat_judge_v2.md 改完 hash 不同），audit trail 自動覆蓋
- 舊 baseline `baseline-post-b23-fix-2026-05-27.json` 標 deprecated（在 case study 註記，檔不刪）

## Non-Goals (optional)

- **不動 chat agent SYSTEM_PROMPT**：agent 自己看 chunk 原文還是 hallucinate（b23 case），那是 agent grounding 問題，屬 `agent-pronoun-grounding` follow-up
- **不動 chunking pipeline**：chunk 大小 / 長距離指代是 chunking 議題（人物名字在前 N 分鐘 chunk、代詞用法在後 chunk），屬 `chunk-level-retrieval-rca-b20-style` 或 chunking-overhaul follow-up
- **不寫 deterministic NLP grader**：中文代詞解析（指代消解）是難 NLP 問題，寫程式準確率不夠引發 false positives；LLM 判斷更穩
- **不擴 dataset**：本 change 只動 judge，dataset 內 expected 內容不變
- **不動 chat_agent_max_iterations / tool_result_max_chars** 等其他 agent loop 參數

## Success Criteria

1. judge prompt schema 多出 `pronoun_attribution_check` 第 4 個 top-level key（條件式）
2. judge_chat_v2.py 組 input payload 時，tool_calls 內每個 element 含 `result_full`（chunk text 完整）
3. b23 重跑 judge 後得到 `pronoun_attribution_check.verdict = "hallucinated"`（rationale 內明確提及「chunk 內代詞指向不是 Leo 王」/「沒有 anchor 支持」）
4. 全集 34 record / 40 turn 重跑落新 baseline，新檔 `provenance.judge_prompt_sha256` 與舊不同
5. 未涉代詞驗證的題目（譬如 b04「節目多久更新一集？」單純資訊題）`pronoun_attribution_check` emit `null`（條件式不跑）
6. 3 個 pytest unit test：grounded scenario / inferred scenario / hallucinated scenario

## Impact

- Affected specs:
  - `rag-eval-judge`（MODIFIED Requirement: judge 評分 schema 多 `pronoun_attribution_check` 第 4 key + input 規範改餵 `result_full`）
- Affected code:
  - Modified:
    - backend/eval/judge_chat_v2.py（組 input payload 改傳 result_full）
    - backend/eval/prompts/chat_judge_v2.md（加 pronoun-attribution rubric + Example 4）
  - New:
    - backend/tests/test_judge_pronoun_attribution.py（3 unit test）
  - Removed: 無
- Affected ops:
  - 全集 baseline 重跑成本 ~$1.5（judge prompt 變約 16× 大，但仍便宜）
  - 落新 baseline 檔，舊檔不刪在 case study 註記 deprecated
- 後續 unblock：`agent-pronoun-grounding` 改完後可用乾淨 judge 量出代詞 grounding 改善
