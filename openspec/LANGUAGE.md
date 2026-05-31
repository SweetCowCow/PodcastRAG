# PodcastRAG Vocabulary

> 專案 canonical 詞彙表。Spectra discuss / propose / apply / archive 過程中提到的概念若在此檔有 entry，必須使用 canonical 名稱；若 user 或 artifact 用了 `avoid` 同義詞，要在 discussion conclusion 標出 vocabulary drift。

## 通則

- 一個概念一個名字。寫到 avoid synonym 不算錯，但要記得在下一個 propose / archive 時統一。
- Legacy term（既有 code / archive 內已固化的命名）可保留原樣，但新 artifact 用 canonical。
- 每個 entry 必含 `definition` / `avoid`（若有）/ `why`（為什麼這樣選）。

---

## Canonical terms

### Arm（benchmark arm）
- **definition**：4-arm benchmark 內的單一「對比組」，譬如 Arm A long-context、Arm B vanilla-rag、Arm C rule-based、Arm D agentic。每個 arm 跑同 dataset、產同 schema 結果可橫向對比。
- **avoid**：「組」「條」「方案」（這些太通用，不知道指 benchmark arm 還是別的）
- **why**：學術 A/B testing 慣用詞，blog 讀者也認

### Golden set
- **definition**：人工 curated 的 eval 題目集合，每題含「正確答案線索」。目前 podcast 場景兩個 golden set：retrieval 用的 `this-not-that-cool.json`（30 題）+ agent 用的 `bakeoff_40.json`（34 題含 multi-turn）。
- **avoid**：「測試資料」（太通用）、「考題」（口語）、「miniset」（除非特指 `_judge_minisset.json` 那 40 題 judge calibration 用的）
- **why**：RAG / eval 社群慣用，配合 `feedback_inventory_docs.md` 規則

### Trace（agent trace）
- **definition**：agent loop 一個 chat turn 跑完的完整紀錄，含 per-round LLM call（latency / token / finish_reason）、per-tool dispatch（name / args / result / latency）、per-stage timing（build_messages / state_load / state_save / history_summary）。型態是 `ChatAgentResult` 內的結構。
- **avoid**：「log」（runtime log 是 logger.info / logger.error 那種；trace 是結構化資料）、「debug info」（太鬆）
- **why**：observability / agent 框架 (OTel / LangSmith) 慣用

### Tool call failure（agent tool 失敗模式）
- **definition**：agent loop 內 tool dispatch 拿到 exception 或語意空回應，導致 LLM 把這狀況翻譯成面向 user 的失敗訊息（譬如「技術問題阻止檢索」「資料存取似乎遇到問題」）。**這跟「LLM 從 noise 推論編造」（hallucination from noise）是兩種不同 root cause**。
- **avoid**：「agent failed」（沒 specify 是 tool 層還是 prompt 層）、「tool error」（混淆 exception 跟 graceful no-result）
- **why**：跟 hallucination 分開診斷才能修對地方

### Hallucination from noise
- **definition**：agent / LLM 拿到一些「跟問題相關但不含答案」的 tool result chunks，從這些 noise 段落推論編造看似合理但實際無依據的答案。譬如 q02 嘻哈冠軍陷阱題，agent 取回大嘻哈評審 chunks（noise）→ LLM 編造「節目中提及歌唱比賽相關話題」。
- **avoid**：「幻覺」（中文通用詞，沒 specify 是 noise-induced）、「LLM 編造」（沒指明來源）
- **why**：跟「沒 retrieve 到就憑空編」（pure hallucination）區分；noise-induced 修法是 prompt grounding 強化，pure 修法是 retrieval coverage 強化

### Refusal aptness
- **definition**：LLM 對「應該拒答」題目（譬如 negative type 陷阱題、out-of-scope 題）禮貌承認資訊不足的能力。Eval 上是 LLM judge 對「拒答行為是否恰當」的維度。
- **avoid**：「禮貌拒答能力」（太口語）、「grounded refusal」（這是 prompt 設計的條款，不是評分維度）
- **why**：跟 grounded refusal（prompt rule）區分；前者是「結果是否合適」後者是「instruction 是否寫了」

### Admin debug gate
- **definition**：endpoint-level 機制讓只有 admin role session 帶特定 query param（譬如 `?debug_trace=true`）才能在 response 收到內部 trace / telemetry。普通 user 帶同 param 不會 4xx，trace 欄位靜默 omit。
- **avoid**：「admin only endpoint」（這 imply 整個 endpoint 限 admin；實際上同 endpoint 普通 user 也用、只是 trace 不回）、「debug mode」（太通用，可能跟 dev env 混淆）
- **why**：明確「同 endpoint 動態 gate」這個 pattern，跟「分流獨立 admin endpoint」區分

### Calibration set
- **definition**：用來驗證 LLM judge 評分跟 human 評分一致性的 dataset（譬如 `_judge_minisset.json` 40 題 + human 1-5 分）。**跟 golden set 不同**：golden set 測 RAG 系統，calibration set 測「判分工具本身」。
- **avoid**：「judge dataset」（太通用）、「測試集」（太鬆）
- **why**：明確分「測系統」vs「測量尺」兩個 purpose

### Stage timing
- **definition**：agent loop 內可拆出獨立度量的處理階段，包含 `build_messages` / `state_load` / `state_save` / `history_summary` / `llm_loop_total`。每個 stage 用 `time.perf_counter()` 取 elapsed_ms。
- **avoid**：「step time」（step 在 agent 內可能指 LLM round，混淆）、「phase」（太抽象）
- **why**：跟 LLM round latency 區分

### Quota
- **definition**：per-user 月度 chat query 次數上限，由 prod admin allowlist 控制。本機 admin 帳號跑 dogfood 消耗 quota 但通常 unlimited。
- **avoid**：「次數限制」（不夠 specific）、「rate limit」（這是 per-request throttling，不是 monthly cap）
- **why**：跟 rate limit 分開

### YAGNI（You Aren't Gonna Need It）
- **definition**：XP 流派核心口號——「不為以後可能用到的需求預先寫程式」。判斷標準：眼下有具體 use case 才寫；只有「以後可能會用」的腦補需求一律不寫。對 ChangeProposal scope 內外的判斷常用。
- **avoid**：「過度設計」「over-engineering」（這兩個是負面標籤，但沒給出可操作的判斷規則；YAGNI 給的是「現在有 use case 嗎」這條明確問句）、「精簡」「lean」（太鬆）
- **why**：避開「腦補需求預先寫」陷阱；Spectra discuss / propose 階段切 scope 經常要援用這條原則。注意：YAGNI **不是**反對所有 generalization——對眼下需求有直接收益的一般化（譬如 SAVEPOINT 防護網對所有 tool 都有效）應該做，YAGNI 擋的是 imaginary need。

### Tool error envelope
- **definition**：agent loop `_dispatch_tool` 回給 LLM 的結構化錯誤格式 `{"ok": false, "kind": "schema|transient|not_found|validation|unknown", "internal_message": "...", "user_hint": "..."}`，取代之前直接 dump `{"error": "ExceptionClassName: msg"}`。LLM 看 `kind` 決策後續行為（譬如 transient 換 tool 試、schema 不要再呼），user 視角只看 `user_hint`，`internal_message` 留給 trace / log debug 用。
- **avoid**：「error result」「error dict」（太通用，沒明示 envelope 是 ok/kind/message/hint 的固定結構）、「tool exception」（exception 是 raise 那刻；envelope 是 catch 後的 dict）
- **why**：把「LLM 看得懂的錯誤分類」「user 看得懂的提示」「engineer 看得懂的內部訊息」三層分開；跟 Tool call failure 一同使用：tool call failure 講「發生什麼事」，envelope 講「怎麼結構化回給 LLM」

### 引用片段卡（SegmentCitationCard）
- **definition**：索引／語意／對話三模式共用的單一引用葉子元件，渲染「一個逐字稿片段」的卡：片段文字 + 高亮（多詞兩色 or server 單色）+ 集標題 + 時間戳 +「播放此段」/「跳到逐字稿」兩顆獨立動作鈕（語意模式另含相關度條）。檔案 `src/SegmentCitationCard.jsx`；`SourceCard` 現為轉呼叫它的 thin wrapper。
- **avoid**：「SourceCard」（legacy 名，現只是 wrapper，新 artifact 用「引用片段卡」）、「來源卡 / 片段卡 / citation chip」三名混用
- **why**：三模式葉子收斂成一個元件，名字也要收斂；配合下方 citation / source / segment 三層語意

### citation（引用）
- **definition**：被 LLM 答案**實際引用**到的片段（對話模式的 `cited_hits`）。顯示張數等於實際引用數，與 retrieval `top_k` 解耦。
- **avoid**：「source」（source 是檢索命中、不一定被引用）、「reference」（太通用）
- **why**：是 source 的子集——「答案真的用到的那些」

### source（來源 / 檢索命中）
- **definition**：檢索（語意／索引）回傳的命中片段，不保證被任何答案引用。語意／索引模式顯示的是 source（到顯示 cap）。
- **avoid**：「citation」（citation 特指被答案引用）、「result」（太通用）
- **why**：跟 citation 區分——是「檢索撈到的全集」，citation 是其中被引用的子集

### segment（逐字稿片段）
- **definition**：逐字稿切成的時間片段（transcript chunk），是 citation / source 指向的底層資料單位。`SegmentCitationCard` 的 `segment` prop 即此。
- **avoid**：「chunk / 片段」未指明層級時混用（內部 retrieval 講 chunk、UI 層講 segment）、「clip」（口語）
- **why**：明確「資料單位」這一層，跟「被引用（citation）／被檢索（source）」的語意層分開

---

## 變更紀錄

- 2026-05-21：建檔。初始 entry 來自 `agent-trace-telemetry` change discuss + propose 過程
- 2026-05-21 晚：`chat-tool-error-isolation` discuss 加入 `YAGNI` + `Tool error envelope`
- 2026-05-31：`unified-segment-citation-card` apply 加入 `引用片段卡（SegmentCitationCard）` + `citation` / `source` / `segment` 三層語意界定
