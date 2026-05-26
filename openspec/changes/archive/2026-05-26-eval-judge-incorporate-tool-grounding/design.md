## Context

PodcastRAG 三模式 eval（keyword / semantic / chat）剛拍版拆分（`docs/eval-strategy.md`）。本 change 只動 chat-rag 那條。

既有 chat-rag eval pipeline（`backend/scripts/run_chat_agent_eval.py` + `extended-multi-turn-40.json` v1）的 grader 邏輯：
- 比 `expected_answer_keywords` 是否 substring 命中 agent answer
- 比 `expected_episode_uuids` 集合 F1
- 既有 LLM judge（`run_llm_judge_multi_turn.py`）只看 question + answer，**不餵 tool I/O**

2026-05-25/26 跑試水 7 題（b22 / b27 / b29 / b11 / b15 / b14 / mt01）暴露五個獨立 gap，記在 `docs/case-studies/chat-rag-dataset-audit-2026-05-25.md`。Schema + 指標清單已 freeze 於 `docs/eval-strategy.md` v2（commit `5593bd7`）。

主要利害關係人：本人（dataset audit + 路線決策）。執行單位：本 change 接 propose → apply 流程。

## Goals / Non-Goals

**Goals：**
- chat-rag dataset 升 v2 schema（must/acceptable 兩層 episode 集合、GT chunk 三層分組、新欄位）
- 三個新指標 grader（`count_consistency` / `answer_contradict_check` / `ordinal_resolution_check`）落地
- LLM judge prompt 重寫，input 含 tool_call I/O snippets（grounding 用），output 三態 refusal_appropriateness + factual_correctness（含 alias 容錯）
- 試水 7 題用 v2 grader 跑出第一個 baseline，落地對比表
- 全 40 題 dataset 一次性 migration script，v1 → v2 schema 自動轉換 + 標 `audit_status: pending`（不自動標 reviewed，等 audit）

**Non-Goals：**
- 不修 retrieval / agent 程式碼（4 個 retrieval/agent pattern 留各自 follow-up change）
- 不改 semantic / keyword 模式
- 不動 Pass^K reliability 跑法
- 不批 audit 全 40 題（本 change 完才開 (c) 階段批 audit）
- 不做 ASR 錯字管線修正
- 不改 admin UI golden-set-maintenance

## Decisions

### D1：dataset schema v2 採「擴展不破壞檔案層級結構」

**選擇**：在現有 `extended-multi-turn-40.json` 同檔案內升 schema，欄位用 `_must` / `_acceptable` 後綴擴展，**不**拆成多檔（每題 1 個 yaml）。

**理由**：
- 單檔 review 容易、diff 直觀
- 現有 runner 預期單檔讀法，遷移成本最低
- 40 題規模單檔還夠用（>200 題才考慮拆檔）

**替代方案**：
- 每題 1 yaml + dataset.yaml index — 過度設計，現規模不需要
- 完全重寫成新檔名 `chat-rag-golden-v2.json` — 多此一舉，舊欄位本來就要移除

### D2：grader 改成 plugin 結構（一個指標一個檔）

**選擇**：`backend/eval/graders/` 目錄下每個指標一個 `.py` module，runner 依 dataset 題目欄位動態選 grader。

**理由**：
- 新指標未來易加（試水就抓到 3 個新指標，後續 audit 全 40 題可能再冒 1-2 個）
- 單元測試容易（grader pure function 輸入 (question_record, agent_response) → score）
- runner 邏輯簡化為「掃題 → 決定該跑哪些 grader → 收 score」

**替代方案**：
- 全部 grader 放 runner 同檔 — 違反開閉原則，每加指標都要動 runner
- 用 LangChain / Ragas 套件 — 過度依賴，三個 grader 自己寫 < 200 行

### D3：LLM judge 一次餵全題，不分指標多次 call

**選擇**：一次 LLM call 同時要 `factual_correctness` + `refusal_appropriateness` + `answer_contradict_check` 三個結構化欄位回來（JSON mode）。

**理由**：
- 一題 1 LLM call 成本約 $0.002（Sonnet 4.6 prompt cache hit）vs 3 call 約 $0.006
- 三指標 share 同樣 context（question + answer + tool I/O），分開呼是浪費 token
- 結構化 JSON 輸出 well-supported

**替代方案**：
- 每指標獨立 LLM call — 成本 3x
- 用 cheap model（Haiku 4.5）每指標獨立 call — 試水太少，不確定 Haiku 對中文 nuanced refusal 判斷夠不夠準，留 follow-up 再 bake-off

### D4：LLM judge 餵 tool I/O 的方式：truncate + 結構化

**選擇**：給 judge 的 prompt 含 `tool_calls` array，每個 element 含 `name` / `args` / `result_summary`（result_full 截 800 chars + 標 `[truncated]` 尾巴）。

**理由**：
- 完整 result_full 動輒 10K+ tokens，judge prompt 太膨脹會吃光 cache benefit
- 800 chars 對 90% case 夠（已驗證試水 7 題 tool result 開頭就含關鍵 chunk text）
- judge 真要看完整 chunk 可從 `chunk_id` 反查 — 但實務上不需要

**替代方案**：
- 不截 result_full — token 爆炸
- 只給 tool name 不給 args/result — judge 等於沒看到 grounding，違反 change 初心

### D5：dataset migration script 採保守策略

**選擇**：v1 → v2 migration script 只做機械轉換（欄位 rename + 重組），**不**自動把 single-tier episode_uuids 拆 must/acceptable，全部標 must，audit_status 全標 `pending`。

**理由**：
- 自動拆 must/acceptable 沒上下文容易標錯（試水證明每題語意都不同）
- pending 狀態強迫 audit 流程不被跳過
- 試水 7 題已 human-verified，migration 後手動覆蓋這 7 題的 v2 entry（從 case study copy）

**替代方案**：
- 大膽自動推導 must/acceptable — 高機率錯標，audit 變 review 工作
- 全部標 reviewed — 違反試水 audit 學到的「自動 generate dataset 必須 human review」(per `feedback_llm_auto_golden_set_needs_review.md`)

### D6：refusal_appropriateness 子型 `refusal_with_correction` 怎麼判

**選擇**：refusal_with_correction = agent refuse 主問題 + 主動補正確 context（如 b27 拒答「冠軍」但補「大嘻哈評審」）。LLM judge prompt 顯式說「refuse 後補正確 context 算 bonus，純 refuse 不扣分」。

**理由**：
- b27 證明這個行為值得 reward（user 拿到更完整 info）
- 不強制要求 correction（純 refuse 也合 appropriateness），是 bonus 而非 penalty

### D7：count_consistency 抓「N 集 / 共 N / N 個」三種 pattern

**選擇**：regex `(\d+)\s*(集|個)|共\s*(\d+)` 抓 answer 內第一個數字，比對 `enumeration_total`。

**理由**：簡單夠用，b11 hallucinate「27 集」會被 catch。

**邊界**：題目本身含數字（如「2024 年」）不算，因為 regex 後接「集 / 個 / 共 N」量詞才 trigger。

## Implementation Contract

### Behavior

eval 跑完後（`python backend/scripts/run_chat_agent_eval.py --dataset chat-rag-golden-v2 --backend https://podcastrag-api.zeabur.app --output /tmp/v2-baseline.json`）：

- 每題輸出 6-9 個獨立 score（依題型決定）
- aggregate 報每指標分母 / 分子 / mean（每題型 sub-group 也獨立報）
- 試水 7 題的 v2 baseline 落到 `docs/case-studies/chat-rag-dataset-audit-2026-05-26-baseline.md`

### Interface / Data shape

**Dataset v2 schema**（詳細 freeze 於 `docs/eval-strategy.md`，這裡只列 contract）：

```json
{
  "show_id": "...",
  "schema_version": "2.0",
  "items": [
    {
      "id": "b15",
      "design_type": "deep_dive",
      "is_multi_turn": false,
      "question": "...",
      "expected_behavior": "answer",
      "expected_answer_summary": "...",
      "expected_answer_aliases": {"電信局": ["公務人員"]},
      "expected_tool_calls_required": ["find_episode_by_ref", "search_within_episode"],
      "expected_tool_args": {"find_episode_by_ref": {"ref_must_match_pattern": "^EP19$|^第19集$"}},
      "expected_episode_uuids_must": ["88f78fbe-..."],
      "expected_episode_uuids_acceptable": null,
      "ground_truth_chunk_ids_must": ["ep:88f78fbe-...@1446.34"],
      "ground_truth_chunk_ids_either": null,
      "ground_truth_chunk_ids_acceptable": null,
      "audit_status": "human-verified-2026-05-26",
      "audit_notes": "..."
    }
  ]
}
```

`turns` array 在 `is_multi_turn: true` 時取代頂層欄位；額外 `carry_from` / `ordinal_resolution_check` 欄位用於 multi_turn_ordinal。

**Grader plugin 介面**：

```python
# backend/eval/graders/<metric>.py
def grade(item: dict, agent_response: dict) -> dict:
    """
    Returns: {
      "score": float in [0.0, 1.0],
      "passed": bool,
      "details": {...}  # 結構化 debug info
    }
    Returns None if grader 不適用此題型（runner 跳過此題的此指標）。
    """
```

**LLM judge prompt 介面**：

input 結構（JSON mode）：
```
{
  "question": str,
  "expected_answer_summary": str,
  "expected_answer_aliases": dict|null,
  "expected_must_contradict_check": str|null,
  "agent_answer": str,
  "tool_calls": [{"name": str, "args": dict, "result_summary": str (800-char truncated)}]
}
```

output 結構：
```json
{
  "factual_correctness": {"score": 0.0-1.0, "rationale": str},
  "refusal_appropriateness": {"verdict": "appropriate"|"should_refuse"|"should_answer", "is_refusal_with_correction": bool, "rationale": str},
  "answer_contradict_check": {"passed": bool, "rationale": str} | null
}
```

### Failure modes

- Grader 拋異常 → runner log warn + 該指標標 `error` 不算分（不阻擋整輪 eval）
- LLM judge 回非合法 JSON → 1 次 retry，再失敗該題 LLM judge 三指標標 `error`
- Dataset 題目欄位缺失（譬如沒 `expected_answer_summary` 但 expected_behavior 是 answer）→ migration script 應在轉換時 fail-loud，runner 跑時遇到視為 `audit_status: pending` 預警
- Backend `/query?debug_trace=true` 503 / 401 → 既有 retry 邏輯不變（3 次 retry，超時跳題）

### Acceptance criteria

1. **試水 7 題 v2 跑分對齊 case study 人工判讀**：
   - b22 retrieval 漏方品融 / 阿名 → `episode_set_f1` < 1.0
   - b27 → 全綠 6/6 指標
   - b29 → `episode_set_f1` 命中 EP134 must（1.0）+ EP143 acceptable miss（bonus 沒拿到）
   - b11 → `count_consistency` fail（answer 27 ≠ enum 26）；其他全綠
   - b15 → 全綠 + `recall@k` = 1.0
   - b14 → `answer_contradict_check` fail（兜兩邊話術）+ `recall@k` 2/3 = 0.67
   - mt01 → t1 全綠；t2 `ordinal_resolution_check` fail
2. **migration script 對全 40 題執行不丟資料**：每題舊欄位都映射到新欄位 OR 標 `pending` 等 audit
3. **單元測試**：每個 grader 至少 3 個 pytest case（pass / fail / inapplicable）
4. **LLM judge prompt 對 cache friendly**：固定 prefix（rules + few-shot examples）至少 1024 tokens 可走 prompt cache（per `claude-api` skill 規範）
5. **新 baseline 文件**：`docs/case-studies/chat-rag-dataset-audit-2026-05-26-baseline.md` 含 7 題 v1 vs v2 grader 對比表 + insight 三點以上

### Scope boundaries

**In scope：**
- `backend/eval/graders/` 4 個新 grader（含 `chunk_recall_grouped.py`）
- `backend/scripts/run_chat_agent_eval.py` runner aggregate 改造 + 新 grader plugin loading
- `backend/eval/datasets/extended-multi-turn-40.json` v2 內容（migration + 試水 7 題手動覆蓋）
- `backend/eval/prompts/chat_judge_v2.md`（新 LLM judge prompt）
- `backend/eval/migrations/v1_to_v2_schema.py` 一次性 script
- `docs/case-studies/chat-rag-dataset-audit-2026-05-26-baseline.md` 落地對比

**Out of scope：**
- Retrieval / agent / SYSTEM_PROMPT 改動
- semantic / keyword 模式
- admin UI / dashboard
- ASR 管線
- Pass^K / K=3 重跑邏輯
- audit 全 40 題的人工 review work（本 change 結束才開 (c) 階段）

## Risks / Trade-offs

- **R1：LLM judge 成本飆升** — v1 跑 40 題 1 次 ≈ $0.05；v2 LLM judge 每題 1 call、Sonnet 4.6、~3K input tokens (cache hit)，估 40 題 ≈ $0.25-$0.50。Acceptable 範圍，但 baseline 重跑或 Pass^K=3 會放大。**Mitigation**：prompt cache 必開、long context truncate tool result、follow-up bake-off Haiku 4.5 是否夠用
- **R2：v2 baseline 數字會「變嚴」** — substring keyword 對語意 nuance 失明，過去高分有水分。v2 baseline 預期會比 v1 低（保守估 -0.1 ~ -0.15），須在 baseline 文件顯式說明「不是 regression，是 metric 升級」
- **R3：migration script 把舊「EP143」標進 acceptable 還是 must 全靠 audit** — 自動轉換只能標 must，audit 才能拆兩層；中間階段（migration 後、全 40 題 audit 前）會有 false-negative 多扣分。Mitigation：baseline 文件只比試水 7 題（已 human-verified），全 40 題等 (c) 階段 audit 完才公布 baseline
- **R4：判 contradict 容易 false-positive** — LLM judge 對「兼具 A 與 B」這種 nuanced 答案判 contradict 可能誤殺正當 multi-faceted 回答。Mitigation：prompt 顯式說「contradict 必須是違反 question 明確 premise，不是答案 cover 多面向」+ 試水 7 題 b14 / b22 兩個 ground truth 例子當 few-shot
- **R5：plugin grader 結構過度設計** — 4 個 grader 不見得需要 plugin pattern。Mitigation：若實際寫起來 < 100 行/grader、共用邏輯多，apply 階段 fallback 改成單檔 module，記為 design drift
- **R6：dataset schema v2 BREAKING 對其他 eval 跑法影響** — `golden_set_freshness` admin endpoint 可能讀舊欄位（per `golden-set-maintenance` spec）。Mitigation：apply 前 grep `expected_answer_keywords` 全 repo，找出所有讀者；確認 admin endpoint 只看 `audit_status` 跟 `last_modified` 不讀 expected_*
