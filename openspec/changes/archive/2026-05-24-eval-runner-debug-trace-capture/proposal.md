## Summary

`backend/scripts/run_chat_agent_eval.py` 沒接 `?debug_trace=true` admin gate（gate 早已在 `agent-trace-telemetry` 2026-05-21 archive），導致 eval result JSON 只有 final answer + tool 名稱 list，**沒 tool args / 沒 tool return**——所有 hallucination diagnose 都是基於 judge reasoning 推測，整套黑箱。本 change 把 trace gate 接上、順手修 `--auth-token` argv leak、重跑 round 1 eval 拿真實 ground truth。

## Motivation

2026-05-24 晚 v3 discuss 浮現的 observability gap：

- `agentic-grounding-prompt-tune-v2` round 1 後剩 5 個 severe case，diagnose 全是「LLM-classifier 看 judge reasoning + final answer 推測 root cause」，沒人看 tool 真的回了什麼
- User 戳破：「不知道 prod 真的回什麼是沒記錄起來，還是你沒觀測到？」結論是**從來沒記錄**
- v3b 的 post-gen citation check 卡這個——沒 tool result 就沒 ground truth 比對
- 順手修：`--auth-token` 走 argv 在 `ps aux` 看得到，違反 `feedback_subprocess_creds_via_env` 規則（本次 session 已實證）

infrastructure 全在：`backend/app/api/query.py::query_show` 的 `debug_trace=true` admin gate（spec `chat-agentic-routing` 第 5 章）已 return 完整 `trace`（含 `tool_calls[].args` + `result_full`、`llm_calls`、`stage_timings`），E2E backdoor session 是 admin 自動過 gate——缺的只是 eval runner 沒呼這個 mode。

## Proposed Solution

### (A) Eval runner 接 debug_trace

修 `backend/scripts/run_chat_agent_eval.py` 的 `_query_chat` helper：query URL 加 `?debug_trace=true`、response 把 `tool_calls` (含 `args` + `result_full`) + `trace.llm_calls` + `trace.stage_timings` 落盤到每 turn 的新 `trace` 欄位。既有 `tool_calls_made` (tool 名 list) 維持不動以 backward-compat（diagnose script 仍可讀舊 result）。

新 result schema：

```
turns[]:
  ... 既有欄位 ...
  tool_calls_made: ['name1', 'name2']         # 不動
  trace:                                        # 🆕
    tool_calls: [{name, args, result_full, result_summary, latency_ms, raised}]
    llm_calls: [{round_index, latency_ms, prompt_tokens, completion_tokens, finish_reason, had_tool_calls}]
    stage_timings: {build_messages_ms, state_load_ms, state_save_ms, history_summary_ms, llm_loop_total_ms}
```

### (B) Auth-token 走 env 不走 argv

- 移除 `--auth-token` argparse positional
- 讀 `os.environ.get("PODCASTRAG_SESSION")`
- script docstring example 更新成 `PODCASTRAG_SESSION="$(cat /tmp/podcastrag_session.txt)" python -m backend.scripts.run_chat_agent_eval ...`
- 順手把 `_ORIGIN_OVERRIDE` 也吃 env `PODCASTRAG_ORIGIN`（同樣道理，避免 origin 漏掉跑出 403）

### (C) 重跑 round 1 eval 拿 ground truth（驗證 task）

prod 目前是 round 1 prompt（commit `4995a2c` revert round 2 後到 `3568530` archive commit），對 `extended-multi-turn-40.json` 跑一次有 trace 版本的 eval，輸出 `backend/eval/results/chat_eval_grounding_v1_with_trace.json`。**不重跑 judge**——judge 結果從 v2 round 1 拿到夠 v3b 用。

## Non-Goals

- **不引 Langfuse / LangSmith / OTel 框架**——拆成獨立 spike (`langfuse-trace-infrastructure-spike`)；本 change 只用既有 `?debug_trace=true` infra
- **不改 backend `/query` endpoint**——gate 邏輯已存在，本 change 純 client 端整合
- **不改 LLM judge script**——judge 不需要 trace，只看 final answer
- **不對歷史 result file backfill trace**——舊 result 該怎樣怎樣，新 result 才有 trace 欄位
- **不重跑 v2 round 2 eval**——已 revert，沒人會 diagnose 那個版本
- **不寫 v3b 的 post-gen citation check**——拆 follow-up change，等 v3a ship 完拿到真實 trace 再 propose
- **不修改 origin header allowed list（CORS）**——origin 設定問題是 backend `FRONTEND_ORIGIN` env 範疇，eval runner 用 env 提供 origin 即可

## Alternatives Considered

- **直接引 Langfuse**：見 Non-Goals。Blast radius 大（新 service / 新 dependency / 隱私評估），ship cycle 跟 v3b 不對齊；獨立 spike 評估比硬塞 v3a 對
- **加 backend log persistence**（譬如把每次 query trace 寫進 PG `query_traces` table）：屬 prod observability infra，跟 eval-time diagnose 是不同 concern；留給 Langfuse spike 一起評估
- **rule-based eval runner 也順手改**：`run.py`（rag-eval-runner spec 涵蓋的那個）不走 chat agent loop，沒 tool I/O 概念，不在本 change scope

## Impact

- Affected specs: `chat-agentic-routing`（add 1 requirement：eval runner SHALL capture debug_trace）
- Affected code:
  - Modified: backend/scripts/run_chat_agent_eval.py
  - New: backend/eval/results/chat_eval_grounding_v1_with_trace.json（重跑產出）
