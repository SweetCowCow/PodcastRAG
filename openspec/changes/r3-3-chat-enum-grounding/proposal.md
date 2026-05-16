## Summary

延伸 R3.3 metadata-filter 的 cross-episode enumeration 行為：chat 答案文字對齊 enumeration list、主題型問題（不只人名 / 日期）也能觸發列舉、為未來 agentic RAG 預留 tool-like 函式結構。

## Motivation

R3.3 ship 後 prod 驗證抓出三個交織的 design gap，使用者體驗矛盾：

1. **Chat 答案文字 vs 卡片數字不一致**：「楊大正是哪幾集的來賓？」chat 文字回「1 集」，但下方卡片正確顯示 **2 集**。原因：answer LLM 只看到 retrieval 撿出的 top-K=8 chunks（其中可能只有 1 集的 chunks），看不到 `enumeration_episodes` 欄位，硬從 chunk 子集推論「1 集」
2. **主題型問題不觸發列舉**：「歌單」單獨輸入完全沒有列舉 section。`entity_extraction` LLM step **已經抽出** `topics: ["歌單"]`，但 `_compute_enumeration_episodes` 只看 guests 與 date_range，topics 欄位被閒置
3. **Rule-pattern fallback 回全 show**：「歌單哪幾集」觸發 rule pattern 後，無 topic filter 直接列全 164 集；spec scenario 原本寫「runs topic-keyword based filter against `episode_description_chunks`」我 Phase 9 偷懶沒做

三個 gap 共用同一條 pipeline：抽 topic → 用 topic 篩集數 → 把篩到的集數給 answer LLM 看。少任何一步整條鏈就斷。

## Proposed Solution

### 1. Chat 文字 grounding

`rag.answer_with_chunks` 新增 `enumeration_episodes` 參數；`llm_prompts.render_answer_prompt` 新增 `enumeration_block` 參數。當有 enumeration 結果時，prompt 在 chunks 區塊**之前**注入結構化條列 block：

```
## 相關集數清單（共 25 集）
這個問題的搜尋結果鎖定以下集數，作為你回答的依據：
1. EP143「從餐廳請客到自家廚房」(2026-04-29, ft. 馬世芳)
2. EP140「高雄美食第二彈」(2026-04-15)
3. EP128「百靈潭...」(2026-03-21)
... （最多 30 集，超過顯示「共 N 集」）
```

選結構化條列（非自然語句）：LLM 對 list 比對自然散文更敏感，數字也更不會亂寫。

### 2. Topic-trigger + 3. Topic-filter SQL

`_compute_enumeration_episodes` 新增 trigger 條件：`entities.topics` 非空也觸發。新增 topic-filter SQL path：

```sql
SELECT DISTINCT e.id, e.title, e.published_at, e.guests, e.ai_summary
FROM episodes e
JOIN episode_description_chunks d ON d.episode_id = e.id
WHERE e.show_id = :show_id
  AND d.text_tsvector @@ to_tsquery('simple', :topic_terms)
ORDER BY e.published_at DESC
```

打 `episode_description_chunks` 而非 `transcript_chunks` 原因：description chunks 是每集的摘要描述，R3.1 已建好 BM25 索引；transcript chunks 每集幾百 row，凡是泛詞被嘴一句就會 hit，列表變雜訊。

Topic terms 來源：優先用 `entities.topics`（LLM 抽好），fallback 把 question 用 jieba tokenize 取 multi-char 詞。兩條來源都過 `TOPIC_STOPWORDS` 過濾（25 詞 hardcoded set 起始）。

**Rule-pattern fallback 行為改變**：「哪幾集」rule 命中時不再回全 show，改走同一條 topic-filter SQL（用 question 自己當 topic terms）。

### 4. Topic + Guest 組合：AND with fallback

當 entities 同時有 guests 與 topics（譬如「馬世芳那幾集講過歌單」）：

- 先試 AND filter（guests + topics 都滿足）
- AND 結果 0 集 → fallback to guest-only filter（使用者顯然關心人，topic 沒對上是其次）
- grounding block prepend 一行「沒有完全相符的集數，列出 [guest] 上過的全部集數」讓 answer LLM 誠實說明

### 5. 結果上限 + 前端漸進顯示

後端不 cap（回完整列表）；前端 EnumerationSection 預設顯示前 10 集，「再顯示 10 集（共 N 集）」按鈕點一次 +10，stepwise 累加；header 顯示「相關集數（共 N 集）」。手機 / 桌機行為一致 — 由使用者點擊節奏自動抑制過長列表。

### 6. Tool-like 函式拆分（預留 agentic RAG 升級路徑）

抽 `backend/app/services/episode_finders.py` 新檔，三個函式：

- `find_episodes_by_guest(db, show_id, guests) -> list[EpisodeRef]`
- `find_episodes_by_topic(db, show_id, topic_terms) -> list[EpisodeRef]`
- `find_episodes_by_date_range(db, show_id, start, end) -> list[EpisodeRef]`

`_compute_enumeration_episodes` 變 dispatcher / combiner，組合三個 finder 結果。Signature 直接可以變未來 agentic RAG 的 tool definition。

### 7. 空結果 UX

若 filter 後 0 集：前端 EnumerationSection 顯示「沒有完全相符的集數」訊息；grounding block 告 LLM「0 集相符」讓文字答案誠實說明沒找到。

## Non-Goals

- **不做 agentic RAG**：LLM 自己決定 tool calls + 自己寫 SQL 留給 R5+。現在只 prepare tool-like signature，不引入 tool execution loop / function calling
- **不維護完整 topic 字典**：B 方案靠 LLM 抽 + 小 stopword set；不走預先字典路線
- **不改 entity_extraction LLM model**：目前 gemini-2.5-flash-lite 跑得好，prompt 不動
- **不擴大 enumeration 到 search mode**：只動 chat path；search 路徑（POST /shows/{id}/search）保持只回 chunks
- **不做 enumeration_episodes pagination**：前端漸進顯示是純 client-side（資料一次拿完），沒走 backend pagination

## Alternatives Considered

- **Agentic RAG（LLM 自己 call tool）**：彈性最高但成本 3-5 倍（多輪 LLM call）+ 延遲飆到 8-15s + tool failure mode 變多。對 PodcastRAG 單 show 規模、單回合題目佔多數的場景，overkill。Tool-like signature 預留升級空間
- **Predefined topic dictionary**：可控但長尾覆蓋差 + 維護成本永久。LLM 抽 + stopword filter 已 99% 涵蓋
- **直接 jieba 切問題當 topic terms（跳過 LLM）**：省 LLM call 但容易抽到「節目」「主持人」這類泛詞 → 需要更大 stopword list 維護
- **Backend 直接 cap LIMIT 30**：避免前端 paging，但對來賓 / 日期型查詢過度限制（譬如某 host 真的固定來賓 50 集就被截）。最終選擇後端不 cap、前端 progressive disclosure

## Impact

- Affected specs:
  - Modified: `rag-query`（`Chat endpoint answers with citations using Tier 2 RAG` requirement 加 grounding + topic-trigger；`Cross-episode enumeration response shape` requirement 加 enumeration_total 欄位 + AND-with-fallback 行為 + 空結果語義；新 requirement「Topic-driven enumeration SQL filter」）
- Affected code:
  - Modified:
    - `backend/app/services/rag.py`（`answer_with_chunks` 加 `enumeration_episodes` param）
    - `backend/app/services/llm_prompts.py`（`render_answer_prompt` 加 `enumeration_block` param）
    - `backend/app/api/query.py`（`_compute_enumeration_episodes` 變 combiner；加 topics trigger + AND/fallback 邏輯；rule-pattern 改走 topic-filter）
    - `backend/app/schemas/query.py`（`ChatResponse` 加 `enumeration_total: int | None`）
    - `src/QueryPage.jsx` 的 `EnumerationSection`（加 displayCount state + stepwise button + header 文案改）
  - New:
    - `backend/app/services/episode_finders.py`（三個 tool-like finder 函式 + `TOPIC_STOPWORDS` 集合 + question→topic_terms helper）
    - `backend/tests/test_episode_finders.py`（finder 單元測試 + stopword filter 測試）
    - `backend/tests/test_chat_enum_grounding.py`（grounding block 渲染測試 + AND fallback 測試）
  - Removed: 無
