## Context

R3.3 metadata-filter（archived 2026-05-16）交付了 entity-driven enumeration（guests / date_range 觸發、列出相符 episodes）+ frontend EnumerationSection。Prod 驗證後抓出三個 design gap：

| Gap | 觀察 | 根因 |
|---|---|---|
| Chat 答案文字 vs enum list 數字不一致 | 「楊大正是哪幾集的來賓？」chat 文字回「1 集」，下方 enum card 顯示 2 集 | `answer_with_chunks` 只看到 retrieval 撿出的 top-K=8 chunks，看不到 `enumeration_episodes` 欄位，硬從 chunk 子集推論集數 |
| Topic-only query 不觸發 enum | 「歌單」單獨輸入沒 enum section | `entity_extraction` 步驟**已抽出** `topics: ["歌單"]`，但 `_compute_enumeration_episodes` 只看 guests / date_range |
| Rule-pattern fallback 回全 show | 「歌單哪幾集」回全 164 集 | Phase 9 偷懶沒做 topic-keyword filter — spec scenario 原本要求對 `episode_description_chunks` 做 topic filter |

三個 gap 同源：把 LLM 抽到的 topic 接上 SQL → 拿 SQL 結果灌進 answer prompt。少一步整條鏈就斷。

**Stakeholders**：產品（使用者體驗 — 答案與列表一致）、後端（retrieval + answer prompt）、前端（漸進顯示 UI）。

**現況依賴**：
- R3.3 `_compute_enumeration_episodes` 在 `backend/app/api/query.py:236`（dispatcher）
- R3.3 `ChatResponse.enumeration_episodes: list[EpisodeRef] | None`
- R3.3 `entity_extraction` AI step (`gemini-2.5-flash-lite`) prod-running
- R3.1 `episode_description_chunks.text_tsvector` GIN index 可用

## Goals / Non-Goals

### Goals

- Chat 答案文字數字 == enumeration_episodes 數字（grounding 後 LLM 不會自己編 N）
- Topic-only query（譬如「歌單」「高雄美食」）能觸發 enum 並回正確 narrow list
- Rule-pattern fallback 不再回全 show，改回 topic-filtered subset
- Topic 與 guest 同題（譬如「馬世芳那幾集講過歌單」）行為合理：先 AND、空集 fallback to guest-only
- Frontend mobile 友善：預設 10 集、stepwise 展開
- 為未來 agentic RAG 升級預留 tool-like 函式 signature

### Non-Goals

- 不引入 LLM tool-calling / function-calling 機制（agentic execution loop 留給 R5+）
- 不維護 predefined topic 字典
- 不擴大 enumeration 到 search mode（只動 chat path）
- 不改 entity_extraction LLM 或 prompt（topic 抽取行為依現有 R3.3）

## Decisions

### Decision 1：grounding 採「prompt 注入結構化條列」而非 post-processing answer

**選擇**：在 `render_answer_prompt` 加 `enumeration_block` 參數；當有 enumeration 結果時 prompt 在 chunks 之前 prepend：

```
## 相關集數清單（共 25 集）
這個問題的搜尋結果鎖定以下集數，作為你回答的依據：
1. EP143「從餐廳請客到自家廚房」(2026-04-29, ft. 馬世芳)
2. EP140「高雄美食第二彈」(2026-04-15)
...
```

註：超過 30 集時 block 內只列前 30、明示 `（顯示前 30 集，共 N 集）`，避免 prompt token 失控。30 × 60 token ≈ 1800 token，gpt-4o-mini context window 充裕。

**Rationale**：LLM 對 list 比對自然散文更敏感，數字也更不會亂寫。Post-processing（regex 抓 chat 答案數字改寫）脆弱且不可預測，會跟 LLM 「重述」行為打架。

### Decision 2：topic-filter SQL 打 `episode_description_chunks.text_tsvector` 而非 `transcript_chunks`

**選擇**：

```sql
SELECT DISTINCT e.id, e.title, e.published_at, e.guests, e.ai_summary
FROM episodes e
JOIN episode_description_chunks d ON d.episode_id = e.id
WHERE e.show_id = :show_id
  AND d.text_tsvector @@ to_tsquery('simple', :topic_terms)
ORDER BY e.published_at DESC
```

**Rationale**：description chunks 是每集的摘要描述（每集 1-N row），語意密集且 R3.1 已建好 GIN index；transcript chunks 每集幾百 row、凡是泛詞被嘴一句就 hit，列表淪為雜訊。Trade-off：title 池目前不參與 enumeration filter（title pool 用 R3.3 RRF weight 0.5 太低意義不大）— 真正缺集數時 description-level recall 已足夠。

### Decision 3：topic terms 來源 priority + stopword 防呆

**選擇**：

1. 優先用 `entities.topics`（LLM `entity_extraction` step 已抽好）
2. 若 entities.topics 空、但 rule pattern (`[哪那]幾集`) 命中：fallback 把 question 用 jieba tokenize 取 multi-char 詞當 topic terms
3. 兩條來源都過 `TOPIC_STOPWORDS` 過濾（hardcoded set 起始）：

```python
TOPIC_STOPWORDS = {
    # 通用泛詞
    "節目", "集數", "集", "主持人", "他們", "我們", "你們",
    "什麼", "怎麼", "為什麼", "有沒有", "多少", "如何",
    # 平台泛詞
    "podcast", "Podcast", "PODCAST",
    # 指示詞
    "這集", "那集", "哪集", "哪幾集", "那幾集",
    # 連接詞
    "或", "及", "與", "的", "了",
}
```

**Rationale**：B 方案（LLM 抽 topic）成本 / 維護最低；LLM 偶爾漏出泛詞用小 stopword set 兜底。未來若漏網率高再升級成 admin UI 可調字典。

### Decision 4：guest + topic 組合 AND with fallback to guest-only

**選擇**：

```
if guests AND topics:
    result = find AND(guests, topics)
    if result is empty:
        result = find_episodes_by_guest(guests)
        mark fallback = True (傳給 grounding block)
elif guests:
    result = find_episodes_by_guest(guests)
elif topics:
    result = find_episodes_by_topic(topics)
elif date_range:
    result = find_episodes_by_date_range(date_range)
elif rule_pattern matched:
    result = find_episodes_by_topic(jieba(question))
```

Date 與 guest / topic 同時出現時（罕見），AND 也適用（譬如「馬世芳 2024 年那集」AND date+guest）。

**Rationale**：使用者問「馬世芳那幾集講過歌單」顯然關心「馬世芳」這個人；若 AND 0 集（馬世芳上的集都沒提到歌單），fallback 給全部馬世芳的集 + 文字明示，比直接回「沒找到」對使用者更有用。

### Decision 5：tool-like signature 抽到新檔，預留未來 agentic 路徑

**選擇**：新增 `backend/app/services/episode_finders.py`，三個獨立 async 函式：

```python
async def find_episodes_by_guest(db, show_id, guests: list[str]) -> list[EpisodeRef]: ...
async def find_episodes_by_topic(db, show_id, topic_terms: list[str]) -> list[EpisodeRef]: ...
async def find_episodes_by_date_range(db, show_id, start, end) -> list[EpisodeRef]: ...
```

每個函式 signature 直接可以變未來 OpenAI function-calling tool definition：name + 一句描述 + JSON schema args + 結構化 return。`_compute_enumeration_episodes` 變 combiner / dispatcher，按 entities 內容決定 call 哪幾個 finder + 怎麼組合（AND / fallback）。

**Rationale**：B 方案現在 ship，D 方案（agentic）未來升級時 finder 函式直接綁進 tool registry 即可、SQL 不用重寫。`episode_finders.py` 抽出去也讓 `query.py`（已 491 行）瘦下來、邏輯獨立檔好測試。

### Decision 6：後端不 cap、前端 stepwise 漸進顯示

**選擇**：後端 SQL 不加 LIMIT（回完整列表）。前端 `EnumerationSection` 元件加 `displayCount` state 預設 10、「再顯示 10 集（共 N 集）」按鈕點一次 +10、累加到全部時 button 變「已全部列出（共 N 集）」disabled。

**Rationale**：使用者自己決定要看多少，N=20 點兩次就到底；N=164 點到第 15 次自然知道「問題太廣，要縮窄」— 心理勸退比硬限制更有效。後端 payload 對 164 集 ≈ 80 KB，可接受。手機 / 桌機行為一致（按鈕點起來累的累計效應對 mobile 自然就是 friction）。

### Decision 7：空結果 UX

**選擇**：

- 後端：filter 後 0 集時，`enumeration_episodes = []`（空 list 而非 None — None 代表「沒觸發 enum」，[] 代表「觸發了但 0 結果」）
- 前端 `EnumerationSection`：當 `enumeration_episodes` 為空 list（非 None）時，顯示 section 含「沒有完全相符的集數」訊息
- Grounding block：0 集時注入「沒有找到相符的集數」單行，讓 answer LLM 文字也誠實說明

**Rationale**：使用者能看到「filter 跑了但 0 結果」與「根本沒觸發 filter」是不同狀態；對 debug 與信任度都重要。

## Risks / Trade-offs

- **Topic-filter 偽陽性**：description chunks 廣義包含集名 + 來賓名 + 主題詞，譬如「歌單」query 可能 hit 集名含「歌單」但內容無關的集。Mitigation：spec scenario 加 example，eval 用 q25 episode_set_recall 對比 R3.3 baseline 0.08；若反而下降代表 SQL 召回太雜要 tune
- **Prompt token 增加**：grounding block 30 集 ≈ 1800 token、+ 既有 chunks block 600-1200 token，total system prompt ~2500-3000 token。gpt-4o-mini context 128k 充裕，但每次 chat cost 略升（每 query +$0.0001 ~ +$0.0003）
- **Stopword set 漏抽 / 過抽**：初始 25 詞可能不夠，prod 跑一陣子才知道。Mitigation：每週用 admin tool 抽樣 entity_extraction 結果，看是否有泛詞洩漏；長期不行才升級成 admin UI 可調字典
- **AND fallback 文字提示打架**：若 prompt 灌「沒有完全相符，列出 X 上的全部集數」而 LLM 還是說「找到 25 集 ft. 馬世芳的歌單集」（無視 fallback flag），grounding 信號相互矛盾。Mitigation：fallback 時 grounding block header 改成「⚠ 沒有完全相符的集數。以下是 [guest] 全部上過的集數（共 N 集）」明示語義，LLM 重複用該語意覆寫

## Migration Plan

無 DB schema 變動（純應用層）。Rollout：

1. ship 後端三件（grounding + topic-trigger + topic-filter SQL + tool-like 拆分）+ 對應 unit test
2. ship 前端 EnumerationSection stepwise（與後端同 deploy）
3. 對 prod 跑 R1.2 eval baseline（q25 / q26 episode_set_recall 對比 R3.3 baseline 0.08 / 0.333）
4. chrome-devtools-mcp 自動驗 + user 人工複測「楊大正是哪幾集的來賓」確認 chat 文字回「2 集」與卡片一致

## Open Questions

- topic-filter SQL 是否要加 LIMIT 100 防止 pathological broad topic（譬如使用者問「節目」這種 stopword 漏網詞）撈全 show？目前 Decision 6 是後端不 cap，但 SQL 級別硬 ceiling 是另一層保險。**傾向：先觀察 prod，若真撈過 100 集（不太可能因為 description chunks 對泛詞召回有限）再加**
- 未來若有複合題（譬如「先找馬世芳上過的集再從中找講美食的」需要 chained query），agentic（D 方案）才能自然處理。**傾向：等真實 prod 出現 ≥3 次這類查詢失敗後再啟動 R5 agentic 規劃**
