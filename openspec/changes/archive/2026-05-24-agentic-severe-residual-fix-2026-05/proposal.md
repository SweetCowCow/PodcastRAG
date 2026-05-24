## Problem

v2 round 1 ship 後剩 5 個 severe hallucination case（severe rate = 0.125，沒過 ≤ 0.10 gate）。v3a `eval-runner-debug-trace-capture` 把 tool I/O 落盤後揭露之前 LLM-classifier 對 5 case root cause **至少 2/5 標錯** — 真實 root cause 是 tool bug / state carry bug，不是 prompt 範疇。

5 case 真實 root cause 分佈：

| Case | trace 真相 |
|------|-----------|
| **b27** negative trap | `find_episode_by_ref(ref='EP1')` SQL 用 `title ILIKE '%EP1%'` substring match，撈到 EP10/EP100/EP146 全部，`ORDER BY published_at DESC` 取最新 = EP146。Tool 完全回錯資料 |
| **mt01 t2** multi-turn | agent 用對 tool (`get_episode_summary`) 但 episode_id `5fb343b5...` 不在 turn 1 enumeration list；state carry 機制有 bug 但具體哪一段（writeback / persist / build_messages）需 telemetry 才知 |
| **b22** cross_episode | 11 個 tool 沒一個能回 host_history；agent 用 `get_show_overview` + `list_episodes` 拿到簡介 + 20 集 list，從 list 推論編造「主持人輪替」 |
| **b12** date_find | `find_episodes_by_date` 回 1 集 EP69，agent 答 EP69 + 補造其他不存在 |
| **b29** negative trap | `search_across_episodes('安身之處')` 回 EP134 chunks；agent 寫 EP134 提到「安身之處」（待人工驗 chunk 是否真有此關鍵詞，疑似 retrieved-then-fabricated）|

## Root Cause

四層各自獨立的問題湊在一起：

1. **SQL substring 沒 word boundary**（b27）
2. **State carry 觀測黑盒**（mt01 t2 — `_build_system_message` 注入 `last_enumeration_episodes` 時沒 log，無法分辨是 writeback fail、persist 沒接好、還是 LLM 偏離指令）
3. **Schema 缺 host-history capability + prompt 沒拒答條款**（b22）
4. **沒 deterministic post-generation 阻止 LLM 把不在 tool result 的 EP / 引號內 quote / show title 寫進 answer**（b12、b29）

## Proposed Solution

### Task 1 — b27 SQL word-boundary fix

`backend/app/services/episode_finders.py` 的 `_BY_REF_EP_NUMBER_SQL`：從 `title ILIKE '%EP1%' OR title ILIKE '%ep1%' OR title ILIKE '%第1集%'` 改成 PG 正規表達式 word-boundary，譬如：

```sql
title ~* (E'(^|[^0-9A-Za-z])(?:EP|第)\\s*' || :n || E'(?:集)?($|[^0-9])')
```

直接比對「EP{n} 後不接數字」即可擋掉 EP10/EP100/EP146 連坐。Unit test 確保 EP1 query 命中 EP1、EP10 query 命中 EP10、EP1 query **不** 命中 EP146。

### Task 2 — mt01 t2 state carry telemetry + diagnose

`backend/app/services/chat_agent/memory.py::_build_system_message`：注入 `last_enumeration_episodes` 時，**只在 admin debug_trace mode**（trace 既有 gate）log 一行包含當前 `state.last_enumeration_episodes` UUID list 跟 user question 的訊息進 `trace.stage_timings` 旁邊新 `stage_meta` 欄位。重跑 mt01 multi-turn eval，看 t2 build 時 state 真的有沒有 carry、有的話 LLM 取了哪個 index。

本 task **不修 state carry 本身** — 只裝 telemetry + 看結果。後續是否修 `_writeback_enumeration_anchor` / `state_store.save` / `_ORDINAL_INSTRUCTION` 措辭、或開獨立 follow-up，**等看到 telemetry 結果再決定**。

### Task 3 — b22 prompt host change refusal

`backend/app/services/chat_agent/prompts.py` 的 SYSTEM_PROMPT 事實 grounding 段補一條：

> 「主持人陣容變化 / 嘉賓輪替 / 主持人變動歷史」這類問題，tool 無 host_history capability；除非 tool result 直接包含「某集明確標記主持人異動」的文字，**必須**拒答「資料庫無主持人變動紀錄」，**禁止**從 episode list / show overview 推論「初期主持人是 X、後期改成 Y」這種編造。

不加新 tool（保留為 follow-up `agentic-host-history-tool`）— prompt refusal 是即時 fix，避免重蹈 round 2 加 example 反而稀釋的覆轍：本條是「禁止」規則而非「示範」，不會跟既有 6 類禁編造規則衝突。

### Task 4 — b12 / b29 post-generation citation scan

agent loop 在 `_emit_final_answer`（或最後 return final answer 前）對 answer 字串做 deterministic scan：

- 收集這 turn 所有 `tool_calls[].result_full` 串成一個大 reference text
- 對 final answer 跑兩種 regex：
  - `EP\d+` token：所有 EP 號碼必須出現在 reference text 內
  - 引號內 quote（`「...」` / `"..."`）：每段 quote 必須 substring match reference text
- 沒命中的 EP / quote **後綴加 `[未驗證]` 標籤**（不 strip 避免破壞 answer 流暢），同時設 response.unverified_count 計數讓 eval 可量
- 不掃 show title（CJK + 標點變體太多容易誤判）— 留 follow-up

mode：先上 **soft mode**（加標籤而非 strip）；觀察期看 false positive 率 + judge severity 變化決定要不要升級 hard mode。

## Non-Goals

- **不修 state carry 本身**（task 2 only 加 telemetry；修法等 telemetry 證據出來才決定，可能成 follow-up）
- **不加 `get_host_changes` 或 `get_host_history` 新 tool**（task 3 走 prompt refusal；新 tool 留 follow-up `agentic-host-history-tool`）
- **不擋 show title 編造**（CJK title 誤判風險高；留 follow-up）
- **不引 Langfuse / LangSmith framework**（v3c spike 仍獨立評估，本 change 用 v3a 既有 `?debug_trace=true` infra）
- **不擴 golden set**（鎖 `extended-multi-turn-40.json` 直接對比 v2 round 1）
- **不改 judge prompt / judge model**（仍 gpt-4o）
- **不重跑 v2 round 2 eval**（已 revert，無對比意義）
- **不修 backend `?debug_trace=true` gate 本身**（既有 spec `Query endpoint exposes trace under admin debug gate` 已涵蓋）

## Success Criteria

跑同份 `extended-multi-turn-40.json` + 同 judge model 重跑後：

- `hallucination_severe_count / 40 ≤ 0.05`（≤ 2 case；v2 round 1 baseline 0.125）
- `hallucination_mild_count / 40 ≤ 0.275`（不惡化）
- `answer_quality_mean ≥ 0.6625`（不退步）
- b27 trace：`find_episode_by_ref(ref='EP1')` 回的 episode title 含 `EP1` 且不是 EP10/100/146 系列
- b22 trace：agent answer 含「資料庫無主持人變動紀錄」或等義拒答
- mt01 t2 trace：新 `stage_meta.last_enumeration_at_build` 欄位存在且 non-null（即使 fix 未動）
- b12 / b29 trace：answer 含「[未驗證]」標籤 marking 不在 tool result 的 EP/quote（task 4 命中）

任一條 fail → 不 archive，回 diagnose round。

## Impact

- Affected specs: `chat-agentic-routing`（add 4 requirements 對應 4 task）
- Affected code:
  - Modified: backend/app/services/episode_finders.py
  - Modified: backend/app/services/chat_agent/prompts.py
  - Modified: backend/app/services/chat_agent/memory.py
  - Modified: backend/app/services/chat_agent/agent.py
  - Modified: backend/app/schemas/query.py
  - New: backend/tests/test_find_episode_by_ref_word_boundary.py
  - New: backend/tests/test_post_gen_citation_scan.py
  - New: backend/eval/results/chat_eval_grounding_v3_with_trace.json
  - New: backend/eval/results/llm_judge_grounding_v3.json
  - New: docs/case-studies/agentic-severe-residual-fix-2026-05-24.md
