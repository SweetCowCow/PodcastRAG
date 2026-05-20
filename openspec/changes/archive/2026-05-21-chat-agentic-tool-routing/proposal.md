## Why

PodcastRAG 目前的 chat pipeline 走「rule-based intent → 單一 `retrieve_hybrid` → LLM 答」（`backend/app/api/query.py::query_show` 的 chat-mode 分支）。三個結構性限制：

1. **多步推理只能靠手寫 if-else**：先找到 EP143、再深挖內文要新增邏輯就得改 query_show 大段程式碼
2. **multi-turn carry context 幾乎沒做**：「他怎麼解釋 RAG？」要從上一輪結果推「他」=「EP143 主講人」目前無法
3. **新能力擴張成本高**：pin 集數 / 跨集對比 / enumeration ordinal reference 都要硬加 rule

`agentic-framework-bakeoff` 已用 3 framework × 40 turn × 6 metric 跑出 framework 決策（A 原生 OpenAI tool calling 量化 4/8 勝、AI-delegate 質化 4.50/5），且實證 multi-turn carry 共通缺陷在三 framework 都 0/4，**問題不是 framework 選擇而是 design**（L1 state 缺 `last_enumeration_episodes` list anchor）。

本 change 把 bake-off 的 prototype + 決策內容正式 ship 到 prod，修 multi-turn carry，並把 B / E 的 port-over（strict schema、tool-eager prompt）一起加入。

## What Changes

### Agent 核心
- 新增 `backend/app/services/chat_agent/` package，把 `backend/scripts/agentic_bakeoff/prototypes/a_native_openai/agent.py` 移為正式版（< 250 LOC 限制改為「以可維護為主」）
- agent loop：原生 OpenAI tool calling，直接打 AI Hub OpenAI-compatible endpoint
- 11 個 tool callable（9 編號）：6 個 stub 換成接既有 service 的 real implementation；`search_across_episodes` 已接 `rag.retrieve_hybrid`、`pin_episode` / `unpin_episode` 寫 Redis L1 state

### Memory L0 + L1
- **L0**：最近 K=3 turn 完整 message + rolling `history_summary` ≤ 300 字（gemini-2.5-flash-lite 增量壓縮，fail-open）
- **L1**：`ChatSessionState` 物件存 Redis、TTL 2h
  - `focused_episode_id`（10 min idle 失效）
  - `last_enumeration_episodes: list[UUID]`（10 min TTL，**新加，修 multi-turn carry**）
  - `session_id`（前端發 UUID v4）
- `find_episodes_by_*` tool 結果**順手寫回 L1**
- `_build_messages` / system prompt 把 `last_enumeration_episodes` 注進 context，附 「使用者說『第 N 集』請對應第 N-1 個 ep_id」instruction

### Port-over（從 bake-off 學到）
- **Tool-eager system prompt**（從 E）：system message 加「先呼 tool 找資料再決定，不要憑印象拒答」，預期降 A 觀察到的 8/40 拒答 + b05 hallucination
- **Strict Pydantic input schema**（從 B）：每個 tool input 用 Pydantic BaseModel，validation 失敗回 LLM 看得懂的 error JSON

### Roll-out
- 加 settings flag `ENABLE_AGENTIC_CHAT`（default `false`）
- Flag = true 時 `query_show` chat-mode 分支走新 agent loop；flag = false 時走既有 rule-based pipeline
- 兩條路徑共存到 eval 驗證通過、prod smoke 過後再翻 default
- search-mode 分支（`payload.mode == "search"`）不改

### Eval 驗證
- 用既有 `backend/eval/datasets/this-not-that-cool.json` golden set 對新 agent loop 跑一輪，跟現有 chat-mode baseline 比 Recall@5 / Faithfulness / answer-match
- 若 Recall@5 下降 > 5pp 或 Faithfulness 下降 > 0.05，停 flag rollout，回 design

## Non-Goals

- **L2 cross-session memory**（user 偏好 / 長期記憶）— 留 Phase 2
- **Frontend response shape 改動** — `landing-and-mode-orchestration-redesign`（parked，49 task）會做 source mode UX + chat 回應 UI，本 change 維持既有 response schema、不動前端
- **`rag.py` 1330 行 module split** — 雖然 roadmap 提過順手做，但範圍太大會壓掉 chat-agent 主軸；獨立成另一個 refactor change 處理
- **ai_steps admin UI for agentic 設定** — agent 用 `answer` step 既有設定，不新增 admin UI；如果之後要調 system prompt 再開
- **Whisper 轉錄 / dispatcher / worker 等周邊系統** — 不動
- **Multi-LLM bake-off**（GPT-4 / Claude 換 model）— 固定 AI Hub gemini-2.5-flash，沿用 bake-off 設定

## Capabilities

### New Capabilities

- `chat-agentic-routing`: agent loop + 11 tool callable + L0/L1 memory + tool-eager prompt + strict schema validation
- `chat-session-state`: `ChatSessionState` 模型 + Redis 存取層 + `last_enumeration_episodes` / `focused_episode_id` 欄位 + 10 min idle TTL 機制

### Modified Capabilities

- `rag-query`: chat-mode 分支加 feature-flag 分流。Flag=true 走 agentic loop；flag=false 保持既有 rule-based pipeline。search-mode 完全不動。

## Impact

- Affected specs:
  - `chat-agentic-routing`（新）
  - `chat-session-state`（新）
  - `rag-query`（modified — chat-mode 分支加 flag 分流）
- Affected code:
  - New:
    - `backend/app/services/chat_agent/__init__.py`
    - `backend/app/services/chat_agent/agent.py`
    - `backend/app/services/chat_agent/tools.py`
    - `backend/app/services/chat_agent/state.py`
    - `backend/app/services/chat_agent/memory.py`
    - `backend/app/services/chat_agent/prompts.py`
    - `backend/tests/test_chat_agent_loop.py`
    - `backend/tests/test_chat_session_state.py`
    - `backend/tests/test_chat_agent_multi_turn.py`
  - Modified:
    - `backend/app/api/query.py`（chat-mode 分支加 flag 分流）
    - `backend/app/core/settings.py`（加 `ENABLE_AGENTIC_CHAT`）
    - `backend/app/schemas/query.py`（chat response 加 optional tool_calls trace 欄位）
  - Removed:
    - 無（feature flag 共存，rule-based pipeline 暫不刪）
