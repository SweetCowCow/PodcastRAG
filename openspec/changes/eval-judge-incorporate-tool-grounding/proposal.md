## Why

`extended-multi-turn-40.json` 的 chat-rag eval pipeline 既有 grader 跟 LLM judge 只比 substring keyword + 答案文字，**完全不看 agent tool I/O**，且 dataset schema 不支援 audit 試水抓到的多種真實情境。試水 7 題（b22 / b27 / b29 / b11 / b15 / b14 / mt01）暴露既有 pipeline 五個 gap：

1. Substring keyword 對「語意同義」(b15「公務人員」≡「電信局」)、「答非所問兜兩邊話術」(b14)、「LLM 數字 hallucination」(b11 tool 回 26 / answer 寫 27) 全失明
2. Dataset 沒有「episode 集合 must / acceptable 兩層」概念，無法區分必中 vs bonus（b29 EP143 是 retrieval 漏掉的 weak signal，全 must 會把這題當 hard fail）
3. Dataset chunk-level GT 不支援 chunk overlap（b14 @1790.18 vs @1808.78 跨 boundary 重疊，原 dataset 把兩者都 must 過嚴）
4. Multi-turn ordinal 題（mt01 t2）的「LLM 是否從前輪 enumeration_state 取對 index」沒有獨立指標，會被併進 answer_match 噪音蓋掉
5. 反問題（b22 / b14）agent 兜「兼具 A 與 B」的話術，現行 grader 無法擋

完整 audit 報告：`docs/case-studies/chat-rag-dataset-audit-2026-05-25.md`。Schema + 指標 freeze 於 `docs/eval-strategy.md` v2。

## What Changes

- 重做 chat-rag golden dataset schema：新增 must/acceptable 兩層 episode 集合、ground_truth_chunk_ids 三層分組、expected_count / expected_top_n_episode_numbers / expected_must_contradict_check / carry_from / ordinal_resolution_check / expected_answer_aliases / expected_answer_summary 欄位；淘汰 expected_answer_keywords
- 新增三個指標 grader：`count_consistency`（regex code）、`answer_contradict_check`（LLM judge）、`ordinal_resolution_check`（code 對 carry_from 解析）
- 既有 grader `answer_factual_correctness` 從 substring keyword 升級為 LLM judge 比對 expected_answer_summary（含 alias 容錯）
- 既有 `refusal_appropriateness` 擴為三態（appropriate / should_refuse / should_answer）+ refusal_with_correction 子型（如 b27）
- 新增兩個 design_type：`leading_question_yes` / `multi_turn_ordinal`
- LLM judge prompt 重寫：含三模式拆分後的 chat 專用 prompt + 顯式餵 tool_call I/O 給 judge 參考（incorporate tool grounding，本 change 名稱由來）
- `run_chat_agent_eval.py` runner 改造：呼叫新 grader、aggregate 報每指標獨立分數（不算跨題型平均）
- **BREAKING**：舊 dataset 欄位 `expected_answer_keywords` / 單層 `expected_episode_uuids` / 單層 `ground_truth_chunk_ids` 不再被 grader 讀取。先做 dataset migration script 把試水 7 題 + 全 40 題轉成 v2 schema
- 試水 7 題的 prod baseline 用新 grader 重跑作為 v2 schema 上線後的第一個 baseline 數字

## Non-Goals

- **不**修 retrieval / agent 程式碼弱點（4 個 retrieval/agent pattern 留各自 follow-up change：`rrf-description-source-weight` / `multi-turn-ordinal-mechanical-resolution` 等）
- **不**改 semantic 模式 / keyword 模式 grader（per docs/eval-strategy.md 三模式拆分，這兩條獨立 backlog）
- **不**動 Pass^K reliability 跑法（K=3 prod 重跑邏輯獨立議題）
- **不**做 ASR 錯字管線修正（短期靠 expected_answer_aliases 容錯）
- **不**改 admin UI golden-set-maintenance（freshness dashboard 不在這 change scope）

## Capabilities

### New Capabilities

（無新 capability — 全部是既有三個 spec 的 requirement 修改）

### Modified Capabilities

- `rag-eval-dataset`: 全套 schema v2（must/acceptable 兩層 + GT 三層分組 + 新欄位 + alias）+ 淘汰 expected_answer_keywords
- `rag-eval-judge`: LLM judge prompt 重寫含 tool I/O grounding；refusal_appropriateness 擴三態 + 子型；新增 answer_contradict_check judge
- `rag-eval-runner`: 新增三個 code grader（count_consistency / ordinal_resolution_check / GT 三層分組 hit 邏輯）；aggregate 報法改為每指標獨立、不跨題型平均

## Impact

- Affected specs: rag-eval-dataset / rag-eval-judge / rag-eval-runner（三者皆 MODIFIED，無 ADDED / REMOVED）
- Affected code:
  - Modified:
    - backend/scripts/run_chat_agent_eval.py（runner aggregate + 新 grader 接線）
    - backend/eval/datasets/extended-multi-turn-40.json（dataset v2 migration 後落地）
    - backend/eval/prompts/（LLM judge prompt 新版；若目錄不存在則建立）
  - New:
    - backend/eval/graders/count_consistency.py（regex 數字一致性 grader）
    - backend/eval/graders/answer_contradict_check.py（LLM judge contradict 包裝）
    - backend/eval/graders/ordinal_resolution.py（解析 carry_from 對 agent resolve episode 比對）
    - backend/eval/graders/chunk_recall_grouped.py（GT 三層分組 recall 計算）
    - backend/eval/migrations/v1_to_v2_schema.py（dataset 一次性 migration script）
    - docs/case-studies/chat-rag-dataset-audit-2026-05-26-baseline.md（v2 grader 第一個 baseline 紀錄）
  - Removed:
    - 無（舊 keyword grader 改成相容 stub 但不再被 runner 呼叫，等下一個 change cleanup）
- 觀測：v2 baseline 跑完後對比 v1 數字會有顯著變動（substring → LLM judge），須在 docs/case-studies/ 落地對比表避免「指標一夕變嚴」被誤判 regression
