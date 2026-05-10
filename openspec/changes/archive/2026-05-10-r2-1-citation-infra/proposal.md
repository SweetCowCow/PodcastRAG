## Why

R1.2 baseline 顯示 Recall@5 = 2.4%，retrieval 已由 R3.1（archived 2026-05-08）提升到 23.8%。但即使 retrieval 找對段落，使用者目前看不到「答案哪一句來自哪一個 source」、「source 周圍的上下文」、「能不能跳到逐字稿那段」— 也無法判斷答案是否值得相信。R1.2 同時暴露 Faithfulness 是當前 RAG 答案最大弱點（mini-set 40 題後段 cross-episode aggregation 8/10 score=1）。R2.1 把答案信任度的基礎建設一次補齊：sources 上下文 + 關鍵字高亮 + 逐字稿 deep-link + LLM prompt 強化（citation 規範 / 拒答 / faithfulness 約束）。R2.2 之後再做 inline `[ref]` 與 hover 互動 polish。

## What Changes

- **後端 `/query` 與 `/shows/{id}/search` response 多 4 個欄位**：每個 source 多回 `before_text`（前 2 個 segment 的 text 拼接）、`after_text`（後 2 個 segment）、`highlights`（PostgreSQL `ts_headline()` 產生的 `<mark>` 標記片段，與 R3.1 jieba tokenizer 一致）、`ai_summary_excerpt`（episode AI 摘要前 60 字截斷）。匿名 search 與登入 query 兩條路徑都回新欄位。
- **LLM answer prompt 改寫**：強制 citation 規範（每句末尾標 `[ref id]` 對應 source 編號）、faithfulness 約束（沒提到的不答 / 不確定就說不知道）、拒答模式（retrieval 沒結果時答「找不到相關內容」而非編造）。
- **後端 citation 解析與降級**：解析 LLM 回應中 `[ref]` 標記，無效 / 不存在的 ref 直接 strip，UI 仍顯示完整 source 列表，不依賴 inline ref 完整度。
- **前端 `<SourceCard>` 升級**：渲染後端回的 `<mark>` 高亮、上下文 before/after 文字、AI 摘要 60 字截斷加「展開」link、「跳到這段內容」button（連到 `TranscriptPage?t=秒`）。
- **TranscriptPage 接收 deep-link**：URL 含 `?t=<秒>` 時自動 scroll 到該 segment 並高亮（顏色或框線、~3 秒淡出）。
- **R1.2 eval 回測**：archive 前必須用現有 mini-set 40 題對比 prompt 改動前後的 Faithfulness（GEval）與 Answer Relevancy。Faithfulness 必須持平或上升才合 archive。
- **雙語 UI 文字**：所有新增 button / popover / fallback message 提供 zh / en 兩版，遵循 CLAUDE.md 規範。
- **不做**：inline `[1] [2]` 編號渲染、答案句子 hover ↔ source 互動高亮、popover 完整化、mobile bottom sheet、無障礙 ARIA — 全延到 R2.2 polish。

## Non-Goals

- **Inline numbered citation 與 hover 互動**：屬 R2.2 polish 範圍。R2.1 只把 backend ref id 機制與 source 列表渲染就緒，UI 層先用簡單 source 卡片（不做答案文字內 anchor / popover）。
- **few-shot examples**：先觀察 prompt 純文字規範 + 拒答邏輯的 Faithfulness 表現；若 R1.2 eval 對比結果不夠好再考慮加。
- **Redis cache 整合**：R4 的 cache key 設計需要綁 sources schema version，但 R4 還沒做、R2.1 不前置；只在 case study 中註記 R4 規劃要對齊。
- **TranscriptPage 反向回到 query 結果的導覽 button**：Browser back 可達到效果，加 button 屬 polish。
- **答案 stream output 與 inline ref 的相容性處理**：R2.1 不渲染 inline ref，所以 stream 與否不影響本 change；R2.2 處理 inline 時再評估。
- **citation_match_rate 監控**：屬 R1.3 dashboard polish 範圍，R2.1 不做。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `rag-query`：(1) search / query response 加 before_text / after_text / highlights / ai_summary_excerpt 四個欄位；(2) LLM answer prompt 強化 citation 規範 + faithfulness + 拒答邏輯；(3) 後端解析 LLM 回應 ref 標記並降級；(4) 改寫既有「Citation click navigates to transcript with highlight」requirement，從 in-app state 改成 URL param `?t=<秒>` deep-link，button 標籤改為「跳到這段內容」/`Jump to transcript`

## Impact

- Affected specs: `rag-query`（modified）
- Affected code:
  - Modified:
    - backend/app/services/rag_query.py
    - backend/app/services/rag_search.py
    - backend/app/api/query.py
    - backend/app/api/shows_search.py
    - backend/app/services/llm_prompts.py
    - src/QueryPage.jsx
    - src/TranscriptPage.jsx
    - src/Shared.jsx
  - New:
    - backend/app/services/citation_parser.py
    - backend/tests/test_citation_parser.py
    - backend/tests/test_rag_query_response_shape.py
  - Removed: (none)
