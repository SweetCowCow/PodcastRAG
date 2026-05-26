## Problem

Multi-turn 對話的後續 turn（t2、t3...）對 t1 已識別到的 episode **失去 focus**，導致 agent 在 t2+：
- 重新查詢時找不到正確 episode（mt02 t2 / mt03 t2）
- 漂移到不相關 episode 並 hallucinate（mt04 t2 走到 EP112 / t3 編造 EP112+EP46）
- 或直接放棄回「請給我 UUID」（mt03 t2 / mt04 t3）

Triage 證據（`docs/case-studies/chat-rag-dataset-audit-2026-05-26-triage-27.md`）：

| item | t1 | t2 行為 | t2 refusal verdict |
|---|---|---|---|
| mt02 | ✅ 答對 EP143 標題 + 來賓 | 「集數 ID 出現問題」放棄 | appropriate (但其實該 refuse RAG 在 EP143 沒提到 — 是巧合) |
| mt03 | ✅ 答對 EP140 兩位來賓 | 「集數標識問題未成功」放棄 | **should_answer** |
| mt04 | ✅ 答對 EP19 來賓蛋頭/李優 | 飄到 **EP112** 列推薦歌（完全錯集）→ t3 編造「EP112+EP46」要 user 確認 | **should_answer** |

跟 `mt01 t2` 的 bug **不同**：mt01 是有 enumeration carry state 但 LLM 取 wrong index（ORDINAL_INSTRUCTION violation，留 `multi-turn-ordinal-mechanical-resolution` 處理）。mt02/03/04 是 carry 機制本身**沒被觸發** — agent 在 t1 識別 episode 後沒寫 focused_episode_id，t2+ 無從 carry。

## Root Cause

`chat-agentic-routing` spec 第 89-98 行已規範 `pin_episode` / `unpin_episode` tools 會寫 `ChatSessionState.focused_episode_id`，但**沒有規範 agent 在 `find_episode_by_ref` 成功 resolve 後該不該自動 pin**。實務上 agent 也沒主動 call `pin_episode`：

| 階段 | 期望 | 實際 |
|---|---|---|
| t1 | `find_episode_by_ref(ref="EP143")` → resolve → **auto-pin EP143** | resolve OK；**沒 pin** |
| t2 | `search_within_episode(query="RAG")` → 自動繼承 `focused_episode_id=EP143` | agent 沒帶 episode_id 也沒可用 focused 狀態 → 走偏 |

兩個獨立但複合的問題：

1. **t1 缺自動 pin**：`find_episode_by_ref` 與 `pin_episode` 行為分離，agent 必須額外推理才會 call pin — 但 SYSTEM_PROMPT 沒 enforce
2. **t2 tool args 缺 focused fallback**：`search_within_episode` / `get_episode_segments` / `get_episode_summary` 等需要 `episode_id` 的 tool，當 agent 未顯式傳入時，dispatcher 不會 default 到 session state 的 `focused_episode_id`

## Proposed Solution

**雙層 mechanical fix（避免 prompt 改動 — 用 tool 層強制 carry）**：

### Layer 1：`find_episode_by_ref` 成功時自動 pin
在 `backend/app/services/chat_agent/tools.py` 的 `find_episode_by_ref` 實作收尾處，當 resolve 到非 None 的 EpisodeRef 時：
- 寫 `ChatSessionState.focused_episode_id = resolved_episode_id`
- 寫 `ChatSessionState.focused_episode_at = now()`
- Tool result envelope 加 `auto_pinned: true` 旗標，讓 agent context 可見

### Layer 2：episode-scoped tool 的 `episode_id` arg 自動 fallback
`search_within_episode` / `get_episode_segments` / `get_episode_summary` 三個 tool 的 dispatcher 預處理：
- 當 agent 未在 args 顯式提供 `episode_id` 時，從 ChatSessionState 載入 `focused_episode_id`
- 若 session 也沒 focused → 維持現行行為（tool 報需要 episode_id）
- Tool result envelope 加 `episode_id_source: "explicit" | "session_focused" | "missing"`

### 同步：`pin_episode` 改為 idempotent + 容許「已 auto-pin 同集」no-op

`pin_episode(episode_id=X)` 當 session 已 `focused_episode_id == X` → 不算 error，回 `{ok: true, already_pinned: true}`。

### 不動的部分

- SYSTEM_PROMPT **不加**「請呼叫 pin_episode」instruction（避免 prompt 飽和 + 確保新 turn 取 ChatSessionState 是 mechanical 行為而非 LLM 自律）
- `unpin_episode` 行為不變
- `ChatSessionState.focused_episode_at` lazy expiry (10 min) 不變
- `chat-session-state` spec 不動（這 change 只動 chat-agentic-routing 的 tool 行為）

## Non-Goals

- **不**修 mt01 t2 ORDINAL_INSTRUCTION bug（屬 `multi-turn-ordinal-mechanical-resolution` 範圍）
- **不**動 RRF retrieval（屬 `retrieval-cross-episode-recall-improvement` 範圍）
- **不**改 dataset schema / LLM judge
- **不**動 SYSTEM_PROMPT（mechanical fix 優先；如 mechanical fix 後仍 fail，再開 prompt change discussion）
- **不**新增 tool（重用既有 11 個 callables）
- **不**改 `chat-session-state` spec 的 ChatSessionState model 結構（只透過既有 `focused_episode_id` 欄位）
- **不**修 mt04 t2 漂到 EP112 的根因（如果 mechanical fix 不夠擋住飄移，留 follow-up — 可能要動 retrieval 或 prompt）

## Success Criteria

mechanical fix ship + prod redeploy 後重跑 v2 triage：

1. **mt02 t2** `refusal_appropriateness.verdict` 不變（appropriate，巧合 — t2 確實該 refuse RAG 不在 EP143），但 tool_calls 含 `search_within_episode(episode_id=<EP143-uuid>)` 而非「請給我 UUID」放棄
2. **mt03 t2** `refusal_appropriateness.verdict` 從 `should_answer` 翻 `appropriate`，agent answer 含 EP140 餐廳推薦資訊（而非「集數標識問題」訊息）
3. **mt04 t2** agent 不再 drift 到 EP112，tool_calls 包含 `search_within_episode(episode_id=<EP19-uuid>)`，answer 內容來自 EP19 而非其他集
4. **mt04 t3** 不再編造「EP112+EP46」，agent 仍 focus 在 EP19
5. **mt01 t2** ordinal bug 行為**不變**（這 change 不修；確認 ordinal_resolution_check 仍 fail = expected baseline）
6. Unit test：`backend/tests/test_chat_agent_multi_turn.py` 新增 4 個 case 覆蓋 auto-pin + episode_id fallback + idempotent pin_episode
7. 既有 multi-turn test 不破壞（`pytest backend/tests/test_chat_agent_multi_turn.py backend/tests/test_chat_session_state.py` 全綠）

## Impact

- Affected specs: `chat-agentic-routing`（MODIFIED — 加 auto-pin behavior + episode_id fallback 規範到 `find_episode_by_ref` / `search_within_episode` / `get_episode_segments` / `get_episode_summary` 相關 requirement；ADD pin_episode idempotency requirement）
- Affected code:
  - Modified:
    - backend/app/services/chat_agent/tools.py（4 個 tool 的 dispatcher 預處理 + post-resolve auto-pin）
  - New:
    - backend/tests/test_chat_agent_epref_carry.py（4 個新 case：auto-pin / episode_id session fallback / pin idempotent / 未 pin 時行為不變）
  - Removed: 無
- 部署：純 Python tool dispatcher 改動 → backend redeploy 即生效（無 DB migration、無 schema change、無 prompt change）
- 觀測：prod redeploy 後重跑 v2 triage 對 mt02/mt03/mt04，確認上述 success criteria 1-5 全達成；落地觀察結果到 case study
