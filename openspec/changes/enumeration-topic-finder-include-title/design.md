## Context

R3.3 ship 完之後（commit chain 截至 `cdaf588`），chat enumeration 路徑由 `_compute_enumeration_episodes`（`backend/app/api/query.py`）統籌；topic 訊號透過 `find_episodes_by_topic`（`backend/app/services/episode_finders.py`）的 SQL 取得，SQL 模板 `_TOPIC_SQL` 只 JOIN `episode_description_chunks` 一張表。

R3.3 Phase 8 已為 `episodes` 表加上 `title_tsvector`（`backend/app/models/episode.py`，jieba + simple analyzer 同 description chunks），由 `backend/app/services/sync.py` 的 `_title_tsv_expr` 維護；該欄位目前只在 search 路徑（`backend/app/services/rag.py` 的 `_title_only_lexical`，R3.3 Phase 8.3）作為三池 RRF 的一池被使用，**chat enumeration 路徑沒接**。

2026-05-17 q25「節目裡有哪些集是歌單？」golden set audit（commit `2a56f64` 已把 expected 從 25 集擴成 27 集）對照 prod chat 結果，發現 23 集 hit 中 21 集在 expected，27 集 expected 中漏 6 集；6 漏撈集（EP19 / EP84 / EP87 / EP89 / EP96 / EP108）共通模式：「歌單」二字只出現在 title，description 完全沒寫。DB 驗證 6 集每集對 description 跑 `to_tsquery('simple', '歌單')` 全部 0 chunk 命中。

## Goals / Non-Goals

**Goals:**

- 讓 `find_episodes_by_topic` 也能撈到「topic 字出現在 title、description 沒寫」的集數
- q25 episode_set_recall 從 21/27 ≈ 0.78 拉到 27/27 = 1.0
- 不引入新欄位、不做 backfill、不動其他 finder
- 用最小 SQL 改動完成（單一 WHERE 子句重寫）

**Non-Goals:**

- 不納入 `episodes.ai_summary` 作為訊號源（見 Decisions / Alternatives）
- 不抓 RSS itunes:keywords / category（見 Decisions / Alternatives）
- 不動 `find_episodes_by_guest`（JSONB array containment 獨立路徑）
- 不動 `find_episodes_by_date_range`（欄位 BETWEEN 過濾獨立路徑）
- 不動 search 路徑（`_title_only_lexical` 已在 R3.3 三池 RRF）
- 不動 entity 抽取（`extract_entities` / `extract_topic_terms_from_question`）
- 不動答 grounding（`format_enumeration_block`）
- 不引入 source weight 或 source flag（下游純 set 操作）

## Decisions

### Decision 1：用 EXISTS-OR 而非 UNION ALL

新的 WHERE 子句：

```sql
FROM episodes e
WHERE e.show_id = :show_id
  AND (
    e.title_tsvector @@ to_tsquery('simple', :tsquery_text)
    OR EXISTS (
      SELECT 1 FROM episode_description_chunks d
      WHERE d.episode_id = e.id
        AND d.text_tsvector IS NOT NULL
        AND d.text_tsvector @@ to_tsquery('simple', :tsquery_text)
    )
  )
ORDER BY e.published_at DESC NULLS LAST
```

**選 EXISTS-OR 而非 UNION ALL 的理由：**

- EXISTS-OR 結果天然 distinct by `episodes.id`，不需要 `DISTINCT ON`
- 原 `_TOPIC_SQL` + `_TOPIC_SQL_OUTER_ORDER` 雙層包裝可以收斂成一層
- 規劃器在 description 命中率高的常見 case 下，EXISTS 早退（first match 即 true），通常比 UNION ALL 兩邊都跑再 dedupe 便宜
- 程式碼可讀性高（只有一個 SELECT）

### Decision 2：共用同一個 `to_tsquery('simple', :tsquery_text)`

兩個 tsvector 都由 jieba tokenize 後送進去，token 結構一致（同步機制：`backend/app/services/sync.py` 的 `_title_tsv_expr` 走 jieba；`backend/app/services/description_indexer.py` 同樣 jieba），所以同一個 tsquery 可同時對兩個 tsvector 安全 match。不需要為 title 另建一條 query。

### Decision 3：不引入 source flag / weight

`find_episodes_by_topic` 簽章維持回 `list[EpisodeRef]`（沒 score 欄位）。下游 `_compute_enumeration_episodes` 做 set intersect / set union，`format_enumeration_block` grounding 把 episode 整集列出來不分來源 — 加 source flag 沒有當前消費者，YAGNI。

### Alternatives Considered

#### Alt A：納入 `episodes.ai_summary`（rejected）

- **救援力**：抽樣本次 6 漏撈集，只有 EP96 的 ai_summary 含「歌單」二字（出現「夏日節拍派對」歌單）；其餘 5 集 ai_summary 寫的是「聊了什麼」（譬如 EP19 寫「從櫻花大戰的主題曲談到福音戰士⋯」），完全不會主動講「這集是歌單集」這個 metadata 標籤。Title 路徑能救 6/6
- **工程成本**：`episodes.ai_summary` 是 plain Text、沒有對應 tsvector column；要納入得新增 column + backfill 全 520 集 + sync 改造 + tsvector 同步維護
- **性質差異**：ai_summary 是 LLM 生的「聊了什麼」內容描述，title 是節目作者下的 metadata 標籤；enumeration 題本質是 metadata 查詢，title 才對症
- **現況**：ai_summary 目前角色只給前端 SourceCard 60 字 excerpt（`backend/app/services/rag.py` 的 `_truncate_ai_summary`），不是 retrieval pool
- **結論**：邊際救援 1/6 + 成本高 10 倍 → YAGNI；未來真出現「ai_summary 救得到 + title 救不到 + description 救不到」的 case，再 propose 獨立 change `enumeration-include-ai-summary`

#### Alt B：節目自己列的標籤 / RSS itunes:keywords / category（rejected）

- **DB / code 現況**：`backend/app/models/episode.py` 沒有 keywords / categories / tags 欄位；`backend/app/services/rss_parser.py` 也沒讀 `itunes:keywords` 或 `<category>`，只抓 `itunes_image` 跟 `itunes_duration`
- **上游驗證（2026-05-17）**：抽樣三個 show 的 RSS（這又沒有很屌 EP143-145、曼報、壹加壹電台），episode 層級的 `itunes:keywords` / `itunes:category text=` / `<category>` 全部空 `[]`
- **結構性原因**：台灣 podcast 託管平台（Firstory / SoundOn）常態 — 大部分創作者不手動填 episode-level tag
- **Show 層級分類**：podcast 分類（藝術 / 文化 / 音樂）是 show-level，對「哪幾集是歌單」這種 episode-level enumeration 沒幫助
- **結論**：上游根本沒填，這條路不存在；非工程選項問題，是資料源沒有

#### Alt C：UNION ALL + DISTINCT ON（rejected）

- 兩邊 subquery + outer DISTINCT ON：code 較長、需要 outer wrapper 補 ORDER BY、規劃器要先 materialize 兩邊再 dedupe
- 跟 EXISTS-OR 同語意但更繁瑣 → 選 EXISTS-OR

## Implementation Contract

**Observable behavior**：對任一 `find_episodes_by_topic(db, show_id, [term1, term2, ...])` 呼叫，回傳的 `list[EpisodeRef]` SHALL 包含所有滿足下列任一條件的 episodes：

1. `episodes.title_tsvector` 對 jieba 展開後的 tsquery 命中，或
2. 該 episode 至少存在一個 `episode_description_chunks` 的 `text_tsvector` 對同一 tsquery 命中

回傳順序：`published_at DESC NULLS LAST`；去重依據：`episodes.id`（天然 distinct）。

**Interface / data shape**：

- 函式簽章不變：`async def find_episodes_by_topic(db: AsyncSession, show_id: uuid.UUID, topic_terms: list[str]) -> list[EpisodeRef]`
- `EpisodeRef` 結構不變（不新增 source flag）
- jieba 預展開邏輯（`enumeration-rule-pattern-broaden` 引入）保留不變

**Failure modes**：

- 空 `topic_terms` 或 stopword-only：維持目前行為，回 `[]`，不打 DB
- tsquery 包含特殊字元（`&|!()<:>\\`）：維持目前 `re.sub` 清理
- DB 例外：bubble up（同現行行為，不靜默吞）

**Acceptance criteria**：

- 單元測試 `backend/tests/services/test_episode_finders.py` 至少新增三組案例：
  - title 命中 + description 沒命中 → 該 episode 出現在回傳
  - description 命中 + title 沒命中 → 該 episode 出現在回傳（回歸測試，確保沒打到舊路徑）
  - title 跟 description 都命中 → 該 episode 只出現一次（dedup 驗證）
- Prod chat path 對 q25「節目裡有哪些集是歌單？」回傳的 `enumeration_episodes` 集合 SHALL ⊇ 新 expected 27 集
- eval runner 跑完全 30 題後 `episode_set_recall` aggregate ≥ 0.94（從 0.88 提升）
- search 路徑 `Recall@5` aggregate ≥ 0.86（不回退）

**Scope boundaries（in scope）**：

- `_TOPIC_SQL` 模板與 `_TOPIC_SQL_OUTER_ORDER` 包裝層的重寫（可能收斂成單一 SQL 常數）
- 對應的 `test_episode_finders.py` 測試新增
- `rag-query` spec 的 enumeration scenarios 文字同步

**Scope boundaries（out of scope）**：

- 不動 `find_episodes_by_guest` / `find_episodes_by_date_range`
- 不動 `_compute_enumeration_episodes` 的組合邏輯
- 不動 `format_enumeration_block` 的 grounding prompt
- 不動 search 路徑（`retrieve_hybrid` / `_title_only_lexical`）
- 不動 `extract_entities` / `extract_topic_terms_from_question`
- 不引入新 column、不做 backfill

## Risks / Trade-offs

- **[Risk] Generic topic term 誤傷**（譬如 LLM 抽出「節目」「介紹」這類）→ Mitigation：`extract_topic_terms_from_question` + LLM entity 抽取都已過 `TOPIC_STOPWORDS` 過濾；prod 驗證階段抽 2-3 個其他 topic 題（「高雄美食」「動漫」）肉眼確認沒誤傷；eval runner 跑全套若 false positive 顯著上升會在 aggregate metric 看到
- **[Risk] EXISTS-OR 規劃器在某些 show 規模 / topic 分佈下可能比 UNION 慢**（理論可能性）→ Mitigation：520 集規模下兩種寫法都是 ms 級；若 prod log 顯示 latency 異常，回退到 UNION ALL 是 2 行 SQL 改動
- **[Trade-off] 不引入 source flag**：未來若要對「title-only vs desc-only」做信心排序就得回頭改 signature；現在沒消費者所以接受

## Migration Plan

1. 改 `_TOPIC_SQL` SQL 模板（單檔修改）
2. 新增 / 更新 `test_episode_finders.py` 三組測試
3. 本地 `pytest backend/tests/services/test_episode_finders.py` 通過
4. Git push → Zeabur 自動 build（必要時 `zeabur service redeploy`）
5. Prod 驗證：對 q25 chat 跑一次，期望 `enumeration_episodes` ⊇ 27 集
6. 跑 eval runner 全套（30 題）對 prod backend：確認 enumeration aggregate ≥ 0.94、Recall@5 不回退
7. 抽樣其他 topic 題（高雄美食 / 動漫 / 雷鬼）肉眼確認沒明顯誤傷
8. /spectra-archive

**Rollback**：純 SQL 模板改動，git revert + redeploy 一條指令還原。無資料層異動。

## Open Questions

- 是否要把 `_TOPIC_SQL` + `_TOPIC_SQL_OUTER_ORDER` 收斂成單一常數？傾向收（EXISTS-OR 已無需 outer wrapper），但 apply 階段視 diff 大小再定
