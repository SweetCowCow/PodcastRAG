## Context

PodcastRAG 現在的 chat pipeline 走「rule-based intent → 單一 retrieve_hybrid → LLM 答」，限制：
- 多步推理（先找到一集再深挖內文）只能靠手寫 if-else
- multi-turn 接 context（「他怎麼解釋 RAG？」要知道「他」=「上一句拍板的 EP143 主講人」）幾乎沒做
- 想加新能力（pin 集數 / 跨集對比）要改 chat router 大段邏輯

主 change `chat-agentic-tool-routing` 要把這層換成 agentic tool routing（LLM 主導決定呼哪個 tool / 呼幾次），但 framework 選擇不該拍腦袋。已知候選 5 個：
- A 原生 OpenAI tool calling（自寫 agent loop）
- B Pydantic AI
- C LangGraph
- D Anthropic SDK
- E Google ADK

剔除 C / D 理由見下方 Decisions；本 change 對 A / B / E 做 bake-off。

相關既有資源：
- `backend/app/services/rag.py::retrieve_hybrid` — 既有 hybrid retrieval（vector + bm25 + reranker），bake-off 的 `search_across_episodes` tool 直接接這個，不重做
- `backend/app/services/episode_finders.py` — guest / topic / date finder 既有
- `backend/eval/datasets/this-not-that-cool.json` — 既有 golden set，挑 26 題覆蓋廣
- `backend/eval/runners/` — 既有 eval runner，metric runner 沿用其 faithfulness / answer match 邏輯

## Goals / Non-Goals

**Goals:**
- 在 3-5 天內產出**有證據**的 framework 決策（不是「我覺得 B 比較順」）
- 同一份 9 tool spec / 30 題 / metric 跑 3 framework，控制變因
- 把方法學固化成 spec，未來其他 bake-off（如 reranker bake-off / chunking bake-off）可沿用
- multi-turn memory 設計（K=3 turn + 300 字 summary + Redis 2h TTL）一併在 prototype 驗證 framework 接得順不順

**Non-Goals:**
- 不選最完美 framework，只選**最適合 PodcastRAG 當下脈絡**的
- 不寫 9 tool 完整實作 — stub 即可（除 7b 接 retrieve_hybrid）
- 不 ship prod、不接 chat UI、不動 ai_steps admin
- 不跑 multi-LLM 對比

## Decisions

### Decision: 候選 framework 剔除 C / D

**選擇**：bake-off 跑 A / B / E 三個，剔除 LangGraph + Anthropic SDK。

**理由**：
- **LangGraph**：graph DSL 強大但 prototype overhead 不對稱 — 寫一個 graph 至少 150 LOC，且 multi-turn memory 要走 `checkpointer` 抽象，調 K=3 truncation 跟 rolling summary 都得繞 framework。我們現在連「要 graph 還是要 loop」都沒答案，先用更輕的 framework 驗證，再決定要不要升級。
- **Anthropic SDK**：AI Hub 不提供 Anthropic-compatible 端點（所有 model 走 OpenAI-compatible），要用 Anthropic SDK 等於要再多接一層 provider abstraction，先排除。未來主 change 若決定要用 Claude，會在 main change 階段獨立評估。

**替代**：跑 5 個全 bake-off — 時程從 3-5 天爆到 8-10 天，效益不對稱。

### Decision: 1 個 LLM provider（固定 AI Hub gemini-2.5-flash 或同等）

**選擇**：bake-off 期間固定 1 個 model，不混 GPT-4 / Claude / Gemini。

**理由**：
- 變因控制：要分辨「framework 差異」與「model 差異」就得固定其中之一
- 成本控制：$1-3 區間 vs 多 model $5-15
- gemini-2.5-flash 在 AI Hub 既有用量、tool calling 行為已知，baseline 穩

**替代**：跑 3 model — 變因爆炸，3 天做不完，且 framework 決策不需要 model 對比就能下。

### Decision: thin prototype < 250 LOC / 份

**選擇**：每份 prototype 限制 < 250 LOC（不含 tool stub / golden set / metric runner 共用部分）。

**理由**：
- 強制聚焦在 framework 本身的 ergonomics，不允許用「我把它包很精美」掩蓋 framework 缺點
- 250 LOC 約等於：agent loop + tool 註冊 + multi-turn memory hook + 跑題 entry point
- 超出代表 framework 抽象與我們需求不對齊，這本身就是 bake-off 訊號

**替代**：不限 LOC — prototype 容易過度工程，比較失準。

### Decision: 9 tool spec（含 retrieve_hybrid 真接 1 個）

**選擇**：9 個 tool 一律先寫 stub，但 `search_across_episodes` 必須接既有 `retrieve_hybrid`。

**理由**：
- 至少 1 個 tool 接真實 retrieval，才能驗證 framework 處理「真的有 latency / 真的會 error」的 tool 是否合理
- 其他 8 個 stub 回固定 fixture data 即可，控制變因
- multi-turn 4 題的 Q2「第三集是什麼內容？」其實會踩到 `get_episode_summary` stub + state carry，已能驗證 framework 接 multi-turn memory 的能力

**替代**：全 stub — 失真，看不出 framework 處理真 latency 的差異。

### Decision: multi-turn memory L0 + L1（不做 L2）

**選擇**：

| Layer | 內容 | 範圍 |
|-------|------|------|
| L0 | 最近 K=3 turn 完整 message + rolling `history_summary` ≤ 300 字 | LLM context window |
| L1 | `ChatSessionState` 物件存 Redis、TTL 2h、含 `focused_episode_id`（10 min idle 失效）、`last_enumeration_episodes`、`session_id` | Session 級 |
| L2 | Cross-session memory（user 偏好 / 長期記憶） | **不做** |

`history_summary` 用 gemini-2.5-flash-lite 增量壓縮，每輪一次，**fail-open**（壓縮失敗不擋主回答）。
`session_id` 由前端發（UUID v4），不在後端自動產生。
`focused_episode_id` 在 10 min 沒新 turn 自動 expire。

**理由**：
- L0 K=3 是文獻常見值，配 300 字 summary 在 chat 多輪測過情境下足夠保留主題 anchor
- L1 Redis TTL 2h 對應一般使用 session 長度，超過視為新對話
- L2 cross-session 屬主 change 後續議題，bake-off 不需要驗

**替代**：K=5 或 K=10 全保留 — context 暴增，且實測在多數 multi-turn 案例 K=3 已夠

### Decision: Metric 算法

**5 量化 metric：**

1. **tool 選對率**：每題人工標 `expected_tool_calls`（list of tool name），跟 framework 實際呼叫的 tool sequence 比。指標 = `precision @ tool name set`（不看順序，看是否該呼的有呼、不該呼的沒呼）。
2. **答題正確率**：沿用 `backend/eval/runners/` 既有 `faithfulness` + `answer_match` 兩個 metric 平均。多 turn 題目每 turn 各算一次再平均。
3. **平均 latency**：per turn ms。從 user message 進去到 final answer 出來（含所有 tool call 來回）。
4. **平均 cost**：per turn USD。從 LLM API response 的 usage token 算（input + output × 對應單價）；tool stub call 不計成本。
5. **multi-turn 通過率**：4 題 multi-turn 完整 conversation 跑完，看 Q2 / Q4 是否答對（Q1 / Q3 視為前置不計分）。指標 = `Q2 + Q4 答對數 / 4`。

**1 質化 metric：**

6. **debug 體驗 1-5 分**，三個面向：
   - trace 可讀性（是否容易看出 tool 呼叫順序、參數、結果）
   - stack trace 清晰度（tool 內 raise exception 時 framework 是否吞掉或傳回 user-friendly trace）
   - 錯誤訊息可讀性（schema validation fail / tool not found / LLM 輸出 garbage 時的訊息）

收集方式：
- **agent auto-trace 文件**：跑 30 題期間 agent 自動收集每題 trace、stack trace 範例、錯誤案例，產出 `docs/case-studies/agentic-framework-bakeoff-2026-05.md` 的「Debug 體驗附錄」section，給 user 評分時對照
- **user 自己跑一輪**：user 從 30 題隨機挑 3 題在本機 repl 重跑，體感打分

兩個都做，最終分數 = `(user score + 文件評分) / 2`

### Decision: 30 題 golden set 組成

**選擇**：26 既有 + 4 新加 multi-turn。

**既有 26 題挑選原則**：從 `backend/eval/datasets/this-not-that-cool.json` 挑覆蓋以下類型：
- guest 找集（4 題）
- topic 找集（4 題）
- date / 集數參考（4 題）
- 單集深挖（4 題）
- 跨集對比（4 題）
- summary 類（3 題）
- show overview（3 題）

**新加 4 題 multi-turn**：

| # | Turn | Question | 測什麼 |
|---|------|----------|--------|
| Q1 | 1 | 「歌單有哪幾集？」 | 觸發 enumeration（find_episodes_by_topic("歌單") 或既有 enumeration 路徑），結果寫進 `last_enumeration_episodes` |
| Q2 | 2 | 「第三集是什麼內容？」 | 測 state carry — 必須從 L1 state 取 `last_enumeration_episodes[2]`，再呼 `get_episode_summary` |
| Q3 | 1 | 「EP143 講什麼？」 | 觸發 find_episode_by_ref("EP143") + get_episode_summary，pin `focused_episode_id` |
| Q4 | 2 | 「他怎麼解釋 RAG？」 | 測 focused pin — 「他」要從 L1 state 取主講人，「RAG」要 search_within_episode(focused_episode_id) |

每題的 `expected_answer` 在 task 4 階段由 golden set author 補（TBD by golden set author）— **不在本 design 階段瞎編**。

### Decision: 19 tasks 分 6 區

見 `tasks.md` 完整列表。摘要：

| 區 | 任務數 | 內容 |
|----|--------|------|
| 1. 共用基礎 | 4 | 9 tool stub / 30 題 golden set / metric runner / cost+latency tracker |
| 2. Prototype A 原生 | 3 | prototype + 跑 30 題 + 收 metrics |
| 3. Prototype B Pydantic AI | 3 | 同上 |
| 4. Prototype E Google ADK | 4 | 同上 + LiteLLM AI Hub adapter |
| 5. 結果分析 | 3 | metrics 比較表 / decision doc / case study |
| 6. discuss 收尾 | 2 | 寫回 chat-agentic-tool-routing design.md / park 本 change |

## 9 Tool Spec

| # | Tool | Input | Output | bake-off 實作 |
|---|------|-------|--------|---------------|
| 1 | `find_episode_by_ref` | `ref: str`（"EP143" / "Axios 那集" / "上一集"） | `episode_id: UUID` 或 `null` | stub fixture |
| 2 | `find_episodes_by_guest` | `name: str` | `list[episode_id]` | 接既有 `episode_finders.find_by_guest` |
| 3 | `find_episodes_by_topic` | `topic: str` | `list[episode_id]` | 接既有 `episode_finders.find_by_topic` |
| 4 | `find_episodes_by_date` | `start: date, end: date` | `list[episode_id]` | 接既有 `episode_finders.find_by_date` |
| 5 | `get_episode_summary` | `episode_id: UUID` | `summary: str`（既有 v0.9 schema） | stub 回 fixture summary |
| 6 | `get_episode_segments` | `episode_id, topic_filter: str \| None` | `list[segment]` | stub fixture |
| 7a | `search_within_episode` | `query: str, episode_id: UUID, k=5` | `list[chunk]` | stub fixture |
| 7b | `search_across_episodes` | `query: str, show_id: UUID, k=8` | `list[chunk]` | **真接 `rag.retrieve_hybrid`** |
| 7c | `search_in_episodes` | `query: str, episode_ids: list[UUID], k=8` | `list[chunk]` | stub fixture |
| 8 | `get_show_overview` | `show_id: UUID` | `overview: str` | stub fixture |
| 9 | `pin_episode` / `unpin_episode` | `episode_id` / `()` | `ok: bool` | 真寫 L1 state（Redis） |

（編號到 9 但實際 11 個 callable，因 7 拆 a/b/c、9 拆 pin/unpin。tool calling 介面是 11 個 function。）

## Risks

- **AI Hub LiteLLM 接 ADK 沒人做過**：task 4.1 第一天先 spike endpoint，30 min 內驗不通就把 E 改成「ADK + Vertex direct（自費 token）」或調整 framework 候選名單，不卡死
- **30 題分不出 framework 差異**：若三個 framework 答題正確率都 > 95%，靠 tool 選對率 + latency + debug 體驗分辨；如果連這些都接近，代表三個都堪用，按 debug 體驗 + LOC 簡單度選
- **質化評分 bias**：user 自評 vs agent 文件評分用平均消化；若兩個分數差 > 2 分，case study 額外寫一段討論為何分歧

## Migration Plan

無 — 本 change 不動 prod，不需 migration。完成後：
1. prototype code 留在 `backend/scripts/agentic_bakeoff/`（不接 main app）
2. decision 寫進 `chat-agentic-tool-routing/design.md`
3. 本 change 用 `spectra park agentic-framework-bakeoff` park 起來，等主 change archive 時一起 archive
