## 0. Spec & Proposal 對應

- Spec requirement A：「find_episode_by_ref SHALL match episode references on word boundaries」→ task 1.x
- Spec requirement B：「Agent loop SHALL log last_enumeration_episodes state at build_messages time under admin debug_trace」→ task 2.x
- Spec requirement C：「System prompt SHALL refuse to fabricate host roster changes」→ task 3.x
- Spec requirement D：「Agent answers SHALL flag unverified EP references and quoted strings」→ task 4.x
- 共用驗證流程（rebuild + redeploy + eval + judge + gate）→ task 5.x
- Archive 前置 → task 6.x

## 1. b27 SQL word-boundary fix

實作 spec requirement「find_episode_by_ref SHALL match episode references on word boundaries」

- [x] 1.1 find_episode_by_ref SHALL match episode references on word boundaries — `backend/app/services/episode_finders.py` 的 `_BY_REF_EP_NUMBER_SQL` 改成 PG word-boundary regex：`title ~* (E'(^|[^0-9A-Za-z])(?:EP|第)\s*' || :n || E'(?:集)?($|[^0-9])')`；params 從三個 ILIKE token 簡化成 `{"show_id":..., "n": n}`
- [x] 1.2 `find_by_ref` 函式內 SQL 呼叫對應更新（params dict 換、不變 return shape）
- [x] 1.3 新增 `backend/tests/test_find_episode_by_ref_word_boundary.py`：4 個 case — EP1 不命中 EP10/EP100/EP146、EP10 不命中 EP100、EP1 命中真實 EP1（fixture）、第3集 命中真實第3集
- [x] 1.4 跑 `backend/tests/test_find_episode_by_ref_word_boundary.py` 全綠 + 跑既有 episode_finders 相關 test 不破

## 2. mt01 t2 state carry telemetry（不修 carry 本身）

實作 spec requirement「Agent loop SHALL log last_enumeration_episodes state at build_messages time under admin debug_trace」

- [x] 2.1 Agent loop SHALL log last_enumeration_episodes state at build_messages time under admin debug_trace — `backend/app/schemas/query.py` 的 `AgentTraceResponse` 新增 optional 欄位 `enumeration_state: dict | None`，shape = `{"last_enumeration_episodes": list[str], "last_enumeration_at": ISO timestamp | None, "user_question": str}`
- [x] 2.2 `backend/app/services/chat_agent/memory.py::_build_system_message` 加可選 `debug_trace` flag 參數；當為 True 時把 state.last_enumeration_episodes + last_enumeration_at + 當輪 user question 收集進 ctx-attached dict
- [x] 2.3 `backend/app/services/chat_agent/agent.py` 主迴圈把 debug_trace flag 傳給 `_build_system_message`、把收集到的 enumeration_state 餵進 `AgentTraceResponse.enumeration_state`；非 admin 路徑保持 None
- [x] 2.4 重跑 mt01 multi-turn 驗：t2 response 含 `trace.enumeration_state.last_enumeration_episodes` 非空 list、`last_enumeration_at` 非 null、`user_question == '第三集是什麼內容?'`
- [x] 2.5 比對 t2 enumeration_state vs t1 tool result 的 episode_id list — 寫進 case study「mt01 t2 root cause 分層判定」段：(A) state 空 → persist 沒接好、(B) state 非空但跟 t1 不同 → writeback 順序錯、(C) state 跟 t1 一樣但 LLM 取錯 index → prompt 措辭問題

## 3. b22 prompt host change refusal

實作 spec requirement「System prompt SHALL refuse to fabricate host roster changes」

- [x] 3.1 System prompt SHALL refuse to fabricate host roster changes — `backend/app/services/chat_agent/prompts.py` 的 SYSTEM_PROMPT 在「事實 grounding 規則 — 重要」段內，6 類禁編造清單之後加一條：「主持人陣容變化 / 嘉賓輪替 / 主持人變動歷史 類問題，除非 tool result 明文包含「某集明確標記主持人異動」的文字，必須拒答『目前資料庫沒有節目主持人變動的明確紀錄，無法回答主持陣容變化』，禁止從 episode list / show overview 推論」
- [x] 3.2 跑 `backend/tests/test_chat_agent_loop.py` 等既有 unit test 不破
- [x] 3.3 prompts.py 五段結構順序不變（role / tool-eager / grounded refusal / 事實 grounding / tool error / tool routing）

## 4. b12 / b29 post-generation citation scan

實作 spec requirement「Agent answers SHALL flag unverified EP references and quoted strings」

- [x] 4.1 Agent answers SHALL flag unverified EP references and quoted strings — `backend/app/services/chat_agent/agent.py` 新增 helper `_annotate_unverified_tokens(answer, tool_calls) -> tuple[str, int]`：concat `tool_calls[].result_full` 成 reference text；用 `re.findall(r'EP\d+', answer)` + `re.findall(r'「[^」]{4,}」|"[^"]{4,}"', answer)` 兩 pass；不命中 reference text 的 token 後綴加 `[未驗證]`；return `(annotated_answer, unverified_count)`
- [x] 4.2 `backend/app/schemas/query.py` 的 `ChatResponse` 新增 `unverified_count: int = 0` 欄位
- [x] 4.3 主迴圈 emit final answer 前呼叫 helper，把 annotated answer + count 寫進 response
- [x] 4.4 新增 `backend/tests/test_post_gen_citation_scan.py`：5 case — EP69 在 reference 內不標、EP70 不在 reference 內標 [未驗證]、長 quote 在 reference 內不標、短 quote (≤3 字) 不掃、`unverified_count` 計數正確
- [x] 4.5 跑 `backend/tests/test_post_gen_citation_scan.py` 全綠

## 5. 部署 + eval + judge + gate

- [x] 5.1 4 個 task 各自 commit（順序：1 → 3 → 4 → 2，先確定的後做的 telemetry-only）
- [x] 5.2 全部 push 到 main 後手動 verify Zeabur 拉到最新 commit（webhook 不穩時 `zeabur service redeploy --id 69eb10360da29f05f49a4b0b -y -i=false`）
- [x] 5.3 等 build RUNNING 後重抓 E2E session、`PODCASTRAG_SESSION=... PODCASTRAG_ORIGIN=https://podcastrag.zeabur.app python3 backend/scripts/run_chat_agent_eval.py --dataset backend/eval/datasets/extended-multi-turn-40.json --backend-url https://podcastrag-api.zeabur.app --label v3-severe-residual --out backend/eval/results/chat_eval_grounding_v3_with_trace.json`
- [x] 5.4 跑 `backend/scripts/run_llm_judge_multi_turn.py --eval backend/eval/results/chat_eval_grounding_v3_with_trace.json --dataset backend/eval/datasets/extended-multi-turn-40.json --out backend/eval/results/llm_judge_grounding_v3.json`；post-process 加 `meta.run_at`
- [x] 5.5 驗 gate 三條：severe ≤ 0.05、mild ≤ 0.275、quality ≥ 0.6625；任一 fail 不 archive，回 diagnose / revert 個別 commit
- [x] 5.6 抽 5 case 看 v3 trace：b27 → find_episode_by_ref 回對 EP / b22 → answer 含「資料庫無主持人變動紀錄」/ b12 → 編造 EP 後綴 [未驗證] / b29 → 編造 quote 後綴 [未驗證] / mt01 t2 → trace.enumeration_state 非空（task 2 只裝 telemetry，severity 可能仍 severe）

## 6. Spectra archive 前置

- [x] 6.1 寫 case study `docs/case-studies/agentic-severe-residual-fix-2026-05-24.md`：4 task 對應 5 case 的 before/after 比較表 + mt01 t2 root cause 分層判定 + gate 結果 + remaining followups
- [x] 6.2 跑 `spectra validate agentic-severe-residual-fix-2026-05` + `spectra analyze` 無 Critical / Warning
- [x] 6.3 release log 草稿（archive 後問 user 是否 commit）
- [x] 6.4 跑 `/spectra-archive agentic-severe-residual-fix-2026-05`
