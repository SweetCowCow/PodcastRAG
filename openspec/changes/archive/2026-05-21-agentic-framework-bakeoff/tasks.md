## 1. 共用基礎建設

- [x] 1.1 在 `backend/scripts/agentic_bakeoff/tools/` 下定義 9 個 tool 的統一 input/output schema（Pydantic BaseModel），其中 8 個 stub 回 fixture data、`search_across_episodes` 接 `app.services.rag.retrieve_hybrid`、`pin_episode` / `unpin_episode` 真寫 Redis L1 state（落實 design.md「9 Tool Spec」表）
- [x] 1.2 在 `backend/scripts/agentic_bakeoff/golden_set/bakeoff_30.json` 整理 30 題 golden set：從 `backend/eval/datasets/this-not-that-cool.json` 挑 26 題覆蓋 7 個類型（guest / topic / date / 單集深挖 / 跨集對比 / summary / show overview），新加 4 題 multi-turn（Q1-Q4，expected_answer 由 golden set author 填，預設 TBD）；每題標 `expected_tool_calls: list[str]`（落實 Requirement: Bake-off uses a fixed 30-question golden set）
- [x] 1.3 在 `backend/scripts/agentic_bakeoff/runner/metric_runner.py` 寫共用 metric runner：跑一份 golden set × 一個 framework adapter，回傳 5 量化 metric（tool 選對率 / 答題正確率 / latency / cost / multi-turn 通過率）+ 收集 trace 給質化評分（落實 Requirement: Metric runner produces five quantitative metrics）
- [x] 1.4 在 `backend/scripts/agentic_bakeoff/runner/cost_latency_tracker.py` 寫 cost + latency tracker：hook LLM API 呼叫前後算 ms、從 response.usage 算 token × 單價（gemini-2.5-flash 預設單價硬編 `MODEL_PRICING` dict）

## 2. Prototype A 原生 OpenAI tool calling

- [x] 2.1 在 `backend/scripts/agentic_bakeoff/prototypes/a_native_openai/agent.py` 寫 < 250 LOC agent loop：直接打 AI Hub OpenAI-compatible endpoint，自己處理 tool call message round-trip + L0 K=3 truncation + history_summary 增量壓縮（gemini-2.5-flash-lite，fail-open）+ L1 Redis state hook
- [x] 2.2 用 metric runner 跑 30 題（含 4 multi-turn），結果寫到 `backend/scripts/agentic_bakeoff/results/a_native_openai_<timestamp>.json`
- [x] 2.3 agent 自動產出 trace 片段（每題 1 條 sample trace + 故意觸發 1 個 tool exception 看 stack trace + 1 個 schema invalid case）寫到 `docs/case-studies/agentic-framework-bakeoff-2026-05.md` 的「Debug 體驗附錄 / A 原生」section

## 3. Prototype B Pydantic AI

- [x] 3.1 在 `backend/scripts/agentic_bakeoff/prototypes/b_pydantic_ai/agent.py` 寫 < 250 LOC：用 Pydantic AI `Agent` + `@tool` decorator + `RunContext`，model 設 OpenAI provider 指向 AI Hub endpoint；L0 / L1 用 Pydantic AI 既有 message history + 自加 Redis state hook
- [x] 3.2 用 metric runner 跑 30 題，結果寫到 `backend/scripts/agentic_bakeoff/results/b_pydantic_ai_<timestamp>.json`
- [x] 3.3 agent 收 trace 寫到 case study 的「Debug 體驗附錄 / B Pydantic AI」section（同 2.3 規格）

## 4. Prototype E Google ADK（含 LiteLLM AI Hub adapter）

- [x] 4.1 **第一天 spike 任務**：寫 `backend/scripts/agentic_bakeoff/prototypes/e_google_adk/litellm_aihub_adapter.py`，用 LiteLLM 包 AI Hub OpenAI-compatible endpoint。完成標準：能成功跑一次 `litellm.completion(model="openai/gemini-2.5-flash", api_base=<aihub>, api_key=<aihub_key>, messages=[...])` 並收到合法 response。30 min 內驗不通要回報並改 framework 候選名單
- [x] 4.2 在 `backend/scripts/agentic_bakeoff/prototypes/e_google_adk/agent.py` 寫 < 250 LOC：用 ADK `LlmAgent` + `FunctionTool`，model 走 4.1 LiteLLM adapter；L0 / L1 用 ADK session memory + 自加 Redis hook
- [x] 4.3 用 metric runner 跑 30 題，結果寫到 `backend/scripts/agentic_bakeoff/results/e_google_adk_<timestamp>.json`
- [x] 4.4 agent 收 trace 寫到 case study 的「Debug 體驗附錄 / E Google ADK」section（同 2.3 規格）

## 5. 結果分析

- [x] 5.1 在 `backend/scripts/agentic_bakeoff/results/comparison.md` 產出三 framework × 6 metric 比較表（5 量化從 3 個 result json 算平均、1 質化從 user score + 文件評分平均），含每個 metric 的 winner 標註
- [x] 5.2 在 `chat-agentic-tool-routing/design.md` 補一個 section「Framework decision (from agentic-framework-bakeoff)」：寫選哪個 + 為什麼選 + 落選的 trade-off（落實 Requirement: Bake-off output is captured in a decision document）
- [x] 5.3 補完 `docs/case-studies/agentic-framework-bakeoff-2026-05.md`：含背景、3 framework 各 5-10 行體感、user 質化評分過程、最終決策摘要

## 6. discuss 收尾

- [x] 6.1 跑 `spectra validate agentic-framework-bakeoff --strict` 確認 spec 格式無 error
- [x] 6.2 跑 `spectra park agentic-framework-bakeoff` 把本 change park 起來；等 `chat-agentic-tool-routing` archive 時一起 archive（不獨立 archive）
