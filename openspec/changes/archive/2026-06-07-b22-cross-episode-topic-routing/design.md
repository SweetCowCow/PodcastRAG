## Context

Chat agent 的主迴圈（chat agent 入口 `run_agent`）每輪呼 OpenAI chat completions，傳 `tools=OPENAI_TOOLS_SPEC` 與 `tool_choice="auto"`，讓 LLM 自由選工具。跨集主題題的「優先 `search_with_topic_prefilter`」指引只寫在 ToolSpec description，gpt-4o 忽略（prod 3/3 選 `search_across_episodes`）。

`search_with_topic_prefilter` 內部：`find_episodes_by_topic_with_source(topic)` 取候選集（已 transcript-aware）→ scope `retrieve_hybrid` top-30 → voyage rerank top-k；topic 無命中時 fallback 全 show retrieve（= `search_across_episodes` 行為）。故 prefilter 是 across 的嚴格超集。

既有 deterministic gate 先例：search-mode 用 `rag._should_skip_routing(question)` 決定要不要跑 episode routing；retrieval 加候選來源用 `enable_guest_dispatch` / `enable_transcript_topic_prefilter` flag kill-switch。本 change 沿用同風格。

## Goals / Non-Goals

**Goals:**

- 讓跨集主題 / narrative 題（標靶：b23）的 agent 第一個工具確定走 `search_with_topic_prefilter`，使 scope + voyage rerank + transcript-aware 集選真正被觸發。
- 高 precision 偵測：不誤路由既有 `expected_tools=search_across_episodes` 的 golden 題。
- flag kill-switch 可一鍵退回現況。

**Non-Goals:**

- 不刪 `search_across_episodes`（16 golden 筆 + result mapper + registry 依賴）。
- 不靠飽和 system prompt 疊 example 當主解。
- 不改 chunk 召回 / voyage / `find_episodes_by_topic` 內部。
- 不改 search-mode 路徑。

## Decisions

### D1. Deterministic first-turn `tool_choice` 強制（主機制）

在 `run_agent` 進入 LLM 迴圈前，先跑偵測器判斷當輪 user question 是否「跨集主題」。命中且 flag on 時，**第一次** LLM call 的 `tool_choice` 設為 `{"type": "function", "function": {"name": "search_with_topic_prefilter"}}`；該強制只作用於第一輪，迴圈後續輪一律恢復 `"auto"`。未命中或 flag off → 第一輪即用 `"auto"`（與現況位元等價）。

理由：`tool_choice` 強制是 OpenAI 原生、deterministic、不碰飽和 prompt；只鎖第一輪保留 agent 後續自由補呼工具（multi-step 題不被綁死）。

### D2. 偵測器：高 precision、低 recall

新增 `chat_agent/routing.py` 的純函式 `should_force_topic_prefilter(question: str) -> bool`：

1. **episode-ref 排除**：question 命中 EP 編號 / `第n集` / 「這集」「上一集」「該集」等 episode-scoped 樣式 → 回 False（這類該走 episode-scoped 工具，不是跨集主題）。
2. **鑑別 token 門檻**：沿用 `episode_finders` 既有 topic-term 抽取（jieba → len≥2 → 去 `TOPIC_STOPWORDS` → 去 `tokenizer.get_show_name_terms()`），結果 ≥2 個鑑別 token → True，否則 False。

寧可漏判（讓某些跨集題仍走 auto）也不誤判（避免把 across_episodes golden 題強制改路由）。門檻與排除樣式在 apply 用 routing-only probe 對 16 筆 golden + b23 雙向驗證後定案。

#### Apply 階段 probe 判讀（2026-06-07，`scripts/b22_routing_probe.py`，已注入 prod tokenizer 使 `get_show_name_terms` 生效）

15 個引用 `search_across_episodes` 的 golden 單元中，14 個偵測 True、1 個（b01）False。逐題判讀：

- **b23（標靶）→ True** ✓；**b01（show_overview，`search_across_episodes` 僅 acceptable）→ False** ✓——節目名 filter 把「《這又沒有很屌》…」縮到只剩 `節目名` 1 token，正確排除。
- **13 題（b20/b21/b22/b29/b32/b33/b37–b42，全 `required=search_across_episodes`）→ True**：這些是道地的跨集主題 / 深掘 / leading 題（b20/b23 本就是本 change 的 RCA 標靶）。dataset 標 `search_across_episodes` 是「改動前的舊期望」。因 prefilter 是 across 嚴格超集（topic 無命中 → 等價 fallback），force 這些題到 prefilter **正是本 change 的目的**、非有害誤判（Risk 段已涵蓋）。**結論：proposal 成功標準「16 筆不誤判」的前提（across 題與 prefilter 題可乾淨切分）不成立——它們是同一種題**；採「偵測命中即正確」判讀，不調門檻。
- **mt02 多輪追問「他怎麼解釋 RAG？」→ True（唯一真疑慮）**：disc=`['解釋','RAG']`、無 episode-ref 樣式，但它是 multi-turn 追問、前輪已 pin 集，`required` 含 `search_within_episode`。偵測器只看當前問句、看不到 pin。**修正＝加 pinned-episode guard（見 D5），不動偵測器門檻**（避免殃及 b23 標靶）。

### D3. flag kill-switch

新增 `enable_topic_routing_nudge: bool = True`（鏡像既有 retrieval flag）。預設 on（這是 bug fix）；`ENABLE_TOPIC_ROUTING_NUDGE=false` 不改 code 退回現況。

### D4. tool_choice 套用點與 multi-turn 互動

只在「當輪第一次」LLM call 套強制；以迴圈內 round index == 0 為界。多輪對話的每個 user turn 各自獨立判斷（偵測器吃當前 user question）。強制工具回傳後若 agent 還要補步驟，後續輪 `"auto"` 讓它自由收尾（grounding / 引用）。

### D5. pinned-episode guard（apply 階段 task 5 probe 新增）

`force_first` 除了「flag on + 偵測命中」外，再 AND 一個條件：**session 無 live focused/pinned 集**（`state.focused_episode_id is None`，`state` 由 `state_store.load` 載入時已套 lazy 過期）。

理由：偵測器是純文字函式、看不到 session 已 pin 的集。multi-turn 追問（如 mt02「他怎麼解釋 RAG？」）文字上像跨集主題題，但被前輪的 pin 限定為 episode-scoped；若強制跨集 prefilter 會蓋掉 pin scope。guard 放在 `run_agent`（能取得 `state`）而非偵測器，維持偵測器純函式可單測。對「先 pin 再問跨集題」也採保守：有 pin 即不 force（pin 蘊含 episode-scoped 意圖、可由 flag 退回）。

## Implementation Contract

- **Behavior**：flag on 且偵測命中時，`run_agent` 當輪第一次 OpenAI call 帶 `tool_choice` 強制 `search_with_topic_prefilter`，其餘輪次與 flag off / 未命中時皆 `"auto"`。偵測未命中或 flag off → 所有輪次 `"auto"`，與現況位元等價。
- **Interface**：
  - `config.Settings` 新增 `enable_topic_routing_nudge: bool = True`。
  - 新檔 `chat_agent/routing.py` expose `should_force_topic_prefilter(question: str) -> bool`（純函式、無 DB、無副作用，方便單測）。
  - `run_agent` 在迴圈前算一次 `force_first = settings.enable_topic_routing_nudge and state.focused_episode_id is None and should_force_topic_prefilter(question)`（含 D5 pinned-episode guard）；第一輪據此選 `tool_choice`。
- **Failure modes**：偵測器對空字串 / 全 stopword 問題回 False（fail-safe 走 auto）；強制的工具名是既有註冊工具，不會產生未知工具。
- **Acceptance criteria**：
  - 單元測試（`test_chat_agent_topic_routing_nudge.py`）：b23 題型 → 偵測 True；EP-ref 題 → False；單鑑別 token 題 → False；flag off → 即使偵測 True 也不強制（驗證傳給 LLM 的 `tool_choice` 參數）。
  - routing probe（apply）：16 筆 `expected_tools=search_across_episodes` golden 題偵測結果列表，確認不誤判（或明列可接受的少數並說明）。
  - prod chat smoke（apply）：b23 題 agent 第一工具 = `search_with_topic_prefilter`、回應引用 EP107。
  - 既有 chat agent 單元測試全綠。
- **Scope boundaries**：in scope = `run_agent` 第一輪 `tool_choice` 決策 + `routing.py` 偵測器 + flag + 驗證。out of scope = `search_across_episodes` 存廢、prompt example、`find_episodes_by_topic` 內部、search-mode。

## Alternatives Considered

- **(B) system-prompt 加 routing 規則**：在 prompts 模組加一條「跨集主題題必用 search_with_topic_prefilter」。否決為主解：system prompt 已飽和，加規則 / example 有 regress 風險（記憶實證），且 tool description 已有同義指引而 LLM 忽略，顯示 prompt 層槓桿弱。至多作為 D1 的輔助補強，非主機制。
- **(C) 退役 / 內化 `search_across_episodes`**：讓跨集搜尋只剩 prefilter（自帶 fallback）。否決：`extended-multi-turn-40.json` 16 筆 `expected_tools` 依賴它、result mapper + registry 也引用，blast radius 過大，且部分 golden 題的 across 期望是否該改需重新 audit，超出本 change 範圍。
- **(D) 把偵測做成 LLM 分類器**：多一次 LLM call 判題型。否決：增延遲 + 成本 + 不 deterministic，與「鏡像既有 deterministic gate」原則相違。

## Risks / Trade-offs

- **偵測器誤判**：把該走 across_episodes 的題強制改路由。緩解：高 precision 設計（雙條件 AND）+ apply routing probe 對 16 golden 驗證 + flag kill-switch。且因 prefilter 是 across 超集，誤判最差也只是退回等價 fallback 行為。
- **topic 品質仍受 LLM 影響**：強制走 prefilter 後，`topic` 引數仍由 LLM 產；entity-only topic 會讓 EP107 排序偏後（見 `topic-prefilter-transcript-aware` 校準）。本 change 只保證「走對工具」，集選品質由該 change 負責；若 prod smoke 顯示 topic 太弱，後續再評估在強制路由時一併提示 LLM 帶上動作詞。
- **過擬合 b23 單題**：緩解：以 16 golden across 題作反向 guard + flag 預設可關。
