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

---

## 變更紀錄

- 2026-05-21：建檔。初始 entry 來自 `agent-trace-telemetry` change discuss + propose 過程
