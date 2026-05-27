## Context

`eval-judge-incorporate-tool-grounding` (2026-05-26 archive) ship 了 LLM judge 三態 schema (`factual_correctness` + `refusal_appropriateness` + `answer_contradict_check`)。本 change 修這個 judge 的兩層盲點：物理層 input 截斷 + prompt 沒代詞驗證 step。

2026-05-27 `eval-baseline-citation-bug-revalidation` case study 內 user 親自聽 EP129 逐字稿 audit 揭露 b23 案例：agent 把呂安故事誤套到 Leo 王身上，judge 給 factual=0.95 完全沒抓。同 case study 又揭露 dataset GT 也有相同 pattern（EP116 @187.48 標錯：那是小老虎跟 Leo 王，dataset auditor 看到「迪拉給我安排演出」就誤判成「迪拉跟 Leo 王」）。這證明 pronoun attribution 是個系統性盲點，不是單一 LLM 不認真。

**現有架構約束**：
- judge prompt `backend/eval/prompts/chat_judge_v2.md` 是 cache-friendly static 內容（≥1024 tokens）+ runtime payload section
- judge `judge_prompt_sha256` 已有 provenance 紀錄機制（per `eval-baseline-citation-bug-revalidation` ADDED requirement）
- chat agent loop 已記錄 `result_full`（per agent-trace-telemetry 2026-05-21 archive），現有資料完整、只是 judge input 沒拿
- judge 模型走 Zeabur AI Hub gemini-2.5-flash-lite（per `PRODUCTION_JUDGE_MODEL default`），context window 大、便宜
- prompt 飽和風險（per memory `feedback_prompt_saturation_more_is_less.md`）— 加 example 要謹慎

## Goals / Non-Goals

### Goals
- 修 judge schema 多 `pronoun_attribution_check` 三態 verdict（grounded / inferred / hallucinated）
- 修 judge input 物理層 — 餵 result_full（chunk text 完整）讓 judge 看得到代詞 anchor
- 修 prompt rubric — 加代詞驗證 step + b23 為 Example 4
- 全集重跑 baseline 留乾淨基準，新檔 `baseline-post-judge-v2-<DATE>.json`

### Non-Goals
- 不動 chat agent SYSTEM_PROMPT（屬 `agent-pronoun-grounding` follow-up）
- 不動 chunking pipeline（chunk 大小 / 長距離指代屬另一條 follow-up）
- 不寫 deterministic NLP grader（中文代詞解析難）
- 不擴 dataset 內容
- 不改其他 judge metrics（factual / refusal / contradict 保持不變）
- 不對 b23 重新 archive（屬 immutable history，case study 已涵蓋）

## Decisions

### 三態 verdict 而非 boolean 或分數

**選**：`pronoun_attribution_check.verdict ∈ {"grounded", "inferred", "hallucinated"}`（純枚舉，無 confidence score）
**因為**：
- 跟現有 `refusal_appropriateness` 三態對稱（appropriate / should_refuse / should_answer），prompt + grader 設計一致
- LLM judge 對 confidence score 通常 calibration 不可信（per b23 給 factual=0.95 就是個反例 — 高信心錯誤）
- grey zone「inferred」獨立成第三態，避免 boolean 把「合理推測」（chunk 寫「Leo 王來表演 / 他唱歌」+ answer 寫「Leo 王唱歌」）誤判成 hallucination

**Alternative considered**：
- Boolean (grounded vs not) — rejected：把 inferred 跟 hallucinated 混在一起會誤殺合理推測
- 0..1 連續分 — rejected：LLM 對 confidence 不穩定，「我有 70% 信心是 hallucinated」其實常是 randomness
- 五態加細分 — rejected：grader 太複雜、邊界 prompt 表達困難

### 修 judge input 餵 result_full 而非加新 retrieval

**選**：改 judge_chat_v2.py 組 input payload 時，tool_calls 內每個 element 改用 `result_full`（chunk text + overlap segment）
**因為**：
- 資料早就有（chat agent loop 已存 `result_full` per ToolCallTrace.result_full）
- 不需要新撈 API call，純改 in-memory dict 組裝
- 餵完整 chunk 才能讓 judge 物理上判讀代詞

**Alternative considered**：
- 加新 retrieval call 讓 judge 自己撈 chunk — rejected：增加 latency、可能跟原本 retrieve 不一致
- judge 自己對 transcript 全集做 search — rejected：太貴
- 保留 result_summary 但加 chunk_text 為 separate field — rejected：schema 變動更大、向後相容差

**Token cost trade-off**：result_summary 500 chars → result_full 平均 ~6000-8000 chars (per 8K cap)，judge input 約變 16×。gemini-2.5-flash-lite per 1M tokens $0.10 input，全 40 turn ~$1.5（vs 舊 ~$1），可接受。

### Prompt 結構：條件式 + 1 個 example

**選**：
- 加 rubric section「Pronoun attribution verification」在現有三個 rubric 之後
- 條件式：只當 expected_answer_summary 涉及多人關係（≥ 2 個專有名詞）時才跑該 check；其他 emit `null`（跟 contradict_check 同 pattern）
- 加 b23 為 Example 4（含 EP129 chunk @261.20 完整文本 + agent 答案 + 正確判定 `hallucinated`）
- **只加 1 個 example**（per `feedback_prompt_saturation_more_is_less.md`「飽和點再加 example 反而 regress」）

**Alternative considered**：
- 無條件對每題都跑 pronoun check — rejected：對「節目多久更新一集？」這種純資訊題沒意義、浪費 token
- 加 3 個 examples（grounded / inferred / hallucinated 各一）— rejected：超出飽和警戒；先用 1 個試水
- 把 pronoun check 寫進 factual rubric 子步驟 — rejected：factual 分數會被代詞 confounder 污染、refusal_appropriateness 已有先例該另立指標

### Baseline 全集重算

**選**：對 prod 跑全 34 record / 40 turn，落新檔 `backend/eval/results/baseline-post-judge-v2-<DATE>.json`
**因為**：
- judge prompt sha 改 → provenance 變 → 舊 baseline 跟新不可比
- 一次性 ~$1.5 投資換清楚對照基準
- 避免後續 follow-up（`agent-pronoun-grounding` 跑分時）要回頭查 judge 版本

**Alternative considered**：
- 只重跑變動題（涉代詞的）— rejected：找哪些題涉代詞需要先跑一次才知道，倒不如全跑
- 不重算、用「new judge 永遠對所有 archive change 重算」原則 — rejected：每個 follow-up 都要重跑成本累加更高

## Implementation Contract

**可觀察的交付**：

1. **judge prompt schema 變動**：`backend/eval/prompts/chat_judge_v2.md` 內 top-level JSON example 多一個 `pronoun_attribution_check` key，spec 出三態枚舉 + null 條件
2. **judge_chat_v2.py 內 input payload 組裝**：tool_calls 內每個 element 含 `result_full` 字串（chunk text + overlap）；現有 `result_summary` 欄位保留（envelope 不變，給 admin debug trace 用）
3. **新 rubric section**：prompt 內 `## Rubric — pronoun_attribution_check` 含 3 verdict 判定準則 + 條件式描述
4. **b23 Example 4**：prompt 末尾的 `## Few-shot examples` 加第 4 個 example，含 EP129 chunk @261.20 full text + agent answer + verdict=hallucinated
5. **新 baseline JSON**：跑 `python -m backend.scripts.run_chat_agent_eval_v2 ... --output backend/eval/results/baseline-post-judge-v2-<DATE>.json`，`provenance.judge_prompt_sha256` 與舊不同
6. **3 個 pytest unit test**：`backend/tests/test_judge_pronoun_attribution.py` 對應 3 個 spec scenario（grounded / inferred / hallucinated）

**驗證 done**：
- pytest 3/3 綠
- judge prompt sha 跑 `python -c "from backend.eval.judge_chat_v2 import load_prompt_sha256; print(load_prompt_sha256())"` 拿到新 hash（與本 change 前的 sha 不同）
- b23 重跑 judge 後在 prod 看 `pronoun_attribution_check.verdict == "hallucinated"`，rationale 內含「呂安」或「chunk 內缺 Leo 王 anchor」或對等語意
- 全集 baseline JSON 存在、provenance 完整、`citation_collector_fix_applied=true`
- 未涉代詞的題目（b01-b04 等 show_overview 題）emit `null`

**Scope in**：judge schema + input payload + prompt rubric + 1 example + baseline 重算 + unit tests
**Scope out**：chat agent SYSTEM_PROMPT、chunking、dataset 內容、其他 judge metrics、deterministic grader

## Risks / Trade-offs

- **[Risk] Prompt 飽和**：加 rubric section + Example 4 可能讓既有 factual / refusal / contradict 評分 regress（per `feedback_prompt_saturation_more_is_less.md`）。 → Mitigation：先在 5 題小集（含 b14 contradict / b15 alias / b27 refuse / b23 pronoun + 1 對照題）做 calibration，確認舊指標分數 ±0.1 內無變動，才跑全集。若 regress 則 revert prompt 改動回到 status quo
- **[Risk] Judge 看 result_full 後對其他指標的影響**：判更嚴或更寬。 → Mitigation：同上 calibration 驗證；具體看 factual / contradict 是否大幅變動
- **[Risk] Token cost 超預期**：result_full 8K cap 對某些題（多 tool 呼叫）可能 16K+。 → Mitigation：cost 監控 baseline 跑分 log，若超 $5 立刻停跑 + 加 cap
- **[Risk] 三類 verdict 邊界模糊**：grounded vs inferred 灰色 case 多。 → Mitigation：用 b23 Example 4 + rubric 準則描述清楚；rationale 必填 ≤80 字繁中說明證據
- **[Trade-off] 條件式 emit null**：靠 LLM 自己判斷「是否涉及多人關係」可能不穩。 → 接受：跟現有 contradict_check 條件式 pattern 一致，prod 表現已驗證可接受

## Migration Plan

1. **Phase 1（無 deploy）**：改 prompt + judge_chat_v2.py + 寫 unit test → pytest 全綠
2. **Phase 2（calibration）**：用 `--filter-ids` 跑 5 題小集（b23 / b14 / b15 / b27 / b20），手工檢查 pronoun 三態判定 + 既有指標無 regress
3. **Phase 3（baseline）**：calibration 通過後跑全集 34 record / 40 turn → 落新 baseline 檔
4. **Phase 4（commit + push + 部分 deploy）**：本 change 變動全在 eval-side（judge 跟 prompts），**不動 prod backend code**，所以**不需要 redeploy**（這是跟其他 change 的關鍵差異 — eval-only change）
5. **Phase 5（case study + roadmap）**：寫 case study `docs/case-studies/judge-pronoun-attribution-baseline-<DATE>.md` + memory + roadmap 同步

**Rollback**：
- Prompt + py code 改動：git revert commit
- Baseline JSON：標 deprecated 不刪
- 因為不動 prod backend，rollback 不需要 redeploy

## Open Questions

- Calibration 階段如果 factual 等指標 regress 怎麼處理？— 預設 revert prompt 改動回原；但極端情況（譬如 factual 變更準）也接受。等實際跑分結果定
- `is_refusal_with_correction` 的 boolean pattern 在 refusal_appropriateness 內運作良好；要不要 pronoun_attribution_check 也加 boolean 子欄位？— 暫不加，三態 verdict 已足。需求出現再開 follow-up
- result_full 餵 judge 後，是否需要對 result_full 也做截斷（譬如 cap 在 16K 避免極長 tool result）？— 預設用 `agentic_tool_result_max_chars=8000` 既有 cap，本 change 不另設
