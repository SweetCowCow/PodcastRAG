## Why

`/spectra-discuss chat-agentic-tool-routing` 收斂時拍板：要把 chat 從現在的「rule + 單一 retrieve_hybrid」升級成 agentic tool routing，但**主 change 不能盲選 framework**。LangChain / LangGraph / Pydantic AI / Google ADK / 原生 OpenAI tool calling 在 multi-turn memory 接得順不順、debug trace 好不好讀、AI Hub（OpenAI-compatible 端點）相不相容、上手成本等面向差異極大，光看 README 無法判斷。

我們需要一個短期 spike：用同一份 9 tool spec、同一個 30 題 golden set、同一套 metric runner，把 3 個候選 framework 各做一份 thin prototype（每份 < 250 LOC），跑出量化 + 質化結果，再讓主 change `chat-agentic-tool-routing` 帶著證據選 framework，而不是憑感覺。

這個 change 性質是 **research / spike**，**不會 ship 到 prod**，完成後產出 decision doc + case study，原型整包 park 起來等主 change archive。

## What Changes

### 共用基礎建設
- 寫 9 個 tool 的 stub spec（input / output schema 統一），其中 `search_across_episodes` 必須接既有 `backend/app/services/rag.py::retrieve_hybrid`，其他可用 stub fixture 回固定資料
- 整理 30 題 golden set：26 題從既有 `backend/eval/datasets/this-not-that-cool.json` pick 概念覆蓋廣的題目，**新加 4 題 multi-turn**（測 last_enumeration_episodes carry + focused_episode pin）
- 寫 metric runner（cost + latency tracker + tool 選對率 + 答題正確率 + multi-turn 通過率 + 質化評分收集）

### 3 份 thin prototype（< 250 LOC / 份）
- **A 原生 OpenAI tool calling**：自寫 agent loop，直接打 AI Hub OpenAI-compatible endpoint
- **B Pydantic AI**：用其 `Agent` + `@tool` decorator + `RunContext` 模式
- **E Google ADK**：透過 LiteLLM wrapper 對 AI Hub（ADK 預設僅綁 Gemini / Vertex，要 adapter）

剔除：
- **C LangGraph** — graph DSL 太重，prototype overhead 不對稱
- **D Anthropic SDK** — AI Hub 不提供 Anthropic-compatible 端點，會需要再多接一層 provider

### 量化 + 質化評估
- **5 量化 metric**：tool 選對率 / 答題正確率 / 平均 latency / 平均 cost / multi-turn 通過率
- **1 質化 metric**：debug 體驗 1-5 分，user 自己跑一輪 + agent 自動產 trace 給 user 看，兩個都做

### 產出
- `openspec/specs/agentic-bakeoff-methodology/spec.md` 紀錄方法學（給未來其他 bake-off 沿用）
- `docs/case-studies/agentic-framework-bakeoff-2026-05.md` 紀錄結果
- decision doc 寫進 `chat-agentic-tool-routing` 的 `design.md`
- 本 change park 起來，等 `chat-agentic-tool-routing` archive 時一起 archive

## Scope

### In
- 9 tool stub（含 1 個接 retrieve_hybrid 真實）
- 30 題 golden set（26 既有 + 4 multi-turn 新加）
- 共用 metric runner + cost/latency tracker
- 3 份 thin prototype（A / B / E）
- 30 題 × 3 framework × 1 LLM provider 各跑一次
- decision doc + case study + methodology spec

### Out
- 不接 `_chat_with_tracker` / `ai_steps` admin UI
- 不上 prod、不寫 frontend
- 不寫 9 tool 完整實作（除 7b 外皆 stub）
- 不做 L2 cross-session memory
- 不跑 multi-LLM（GPT-4 / Claude / Gemini）對比 — 固定 1 個 provider（AI Hub 走 gemini-2.5-flash 或同等價位 model）
- 不評估 streaming 行為（agent loop 跑完整輪再返）

## Estimate

- **時程**：3-5 天 spike
- **任務數**：19 tasks 分 6 區
- **LLM 成本**：估算 $1-3 區間（30 題 × 3 framework × 約 2-3 tool call × ~$0.005/call，視最終 model 選擇浮動）
- **不擴張 infra**：本機 + AI Hub key 即可，不動 Zeabur / Redis / Postgres

## Open Questions（已收斂）

- ~~multi-turn 題數~~ → **拍板 4 題**：Q1/Q2 enumeration carry、Q3/Q4 focused pin
- ~~質化評分由誰跑~~ → **拍板兩個都做**：user 自己跑一輪打分 + agent 自動產 trace 文件給 user 看

## Risks

- **AI Hub LiteLLM adapter 沒寫過**：Google ADK 接 AI Hub 可能踩到 endpoint 格式 / auth header 不對的雷，第一天先做 spike 驗證 endpoint 活
- **30 題不夠分辨**：若 3 framework 在 30 題上分不出來，可能要再加 10-20 題；先跑再說，不預先擴
- **質化評分主觀**：user 自評會有 framework 偏好 bias，靠 agent auto-trace 文件 + scoring rubric 抵消
