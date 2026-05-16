## 1. Tool-like finder 函式抽到新檔（落實 `Topic-driven enumeration SQL filter`）

- [x] 1.1 新增 `backend/app/services/episode_finders.py` 落實 `Topic-driven enumeration SQL filter`：定義 `TOPIC_STOPWORDS: set[str]` 起始 25 詞（per design Decision 3 列表）+ helper `extract_topic_terms_from_question(question: str) -> list[str]`（jieba tokenize → 過長度 ≥2 → 過 TOPIC_STOPWORDS）
- [x] 1.2 新增 `find_episodes_by_guest(db, show_id, guests: list[str]) -> list[EpisodeRef]`：SQL 用 `guests @> CAST(:guests AS jsonb)`、ORDER BY published_at DESC NULLS LAST；guests 空 list 時直接回 []
- [x] 1.3 新增 `find_episodes_by_topic(db, show_id, topic_terms: list[str]) -> list[EpisodeRef]`：SQL `SELECT DISTINCT e.* FROM episodes e JOIN episode_description_chunks d ON d.episode_id = e.id WHERE e.show_id = :show_id AND d.text_tsvector @@ to_tsquery('simple', :tsquery_text)`，tsquery_text = topic_terms 用 ` | ` join；ORDER BY e.published_at DESC NULLS LAST；topic_terms 空 list 時回 []
- [x] 1.4 新增 `find_episodes_by_date_range(db, show_id, start: datetime, end: datetime) -> list[EpisodeRef]`：SQL `WHERE published_at BETWEEN :start AND :end`；ORDER BY published_at DESC NULLS LAST
- [x] 1.5 新增 `backend/tests/test_episode_finders.py`：(a) `test_topic_stopwords_strips_generic_tokens`（spec scenario「TOPIC_STOPWORDS strips generic tokens」example 為 fixture）；(b) `test_find_by_guest_uses_jsonb_containment`（mock db.execute 驗 SQL 包含 `guests @> CAST(:guests AS jsonb)`）；(c) `test_find_by_topic_uses_description_chunks_tsvector`（mock 驗 SQL 包含 `episode_description_chunks` JOIN + `text_tsvector @@`）；(d) `test_find_by_topic_does_not_touch_transcript_chunks`（mock 驗 SQL **不含** `transcript_chunks`）；(e) `test_find_by_date_range_between_bound`（mock 驗 SQL `BETWEEN`）

## 2. `_compute_enumeration_episodes` 改成 combiner / dispatcher（落實 `Cross-episode enumeration response shape` MODIFIED + `Chat endpoint answers with citations using Tier 2 RAG` MODIFIED）

- [x] 2.1 修改 `backend/app/api/query.py` `_compute_enumeration_episodes` 落實 `Cross-episode enumeration response shape` MODIFIED：把現有 inline SQL 邏輯換成呼叫 episode_finders 三個函式。新增 trigger 條件：`entities.topics` 非空也觸發
- [x] 2.2 實作 AND-with-fallback 組合邏輯：guests + topics 同時非空時先 `set(find_by_guest) & set(find_by_topic)` 取交集；空集時 fallback to find_by_guest only，傳回 tuple `(episodes, fallback_marker: Literal["none","guest_only"])`
- [x] 2.3 Rule-pattern 命中但 entities 空時：用 `extract_topic_terms_from_question(question)` 拿 topic_terms → 呼叫 `find_episodes_by_topic`。**廢掉**現有「無 filter → 回全 show」這條路徑
- [x] 2.4 回傳型改為 `(list[EpisodeRef] | None, int | None, fallback_marker)`：第一個是 list（empty list 表示觸發但 0 集；None 表示未觸發）；第二個是 enumeration_total（== len(list) 因為後端不 cap）；第三個是 fallback marker 供 grounding block 用
- [x] 2.5 更新 chat handler 把新增的 enumeration_total 寫進 ChatResponse；fallback_marker 傳給 `answer_with_chunks` 用

## 3. Schema 新增 enumeration_total（落實 `Cross-episode enumeration response shape` MODIFIED 的 enumeration_total 欄位）

- [x] 3.1 修改 `backend/app/schemas/query.py` `ChatResponse` 新增 `enumeration_total: int | None = None`；維持 `enumeration_episodes: list[EpisodeRef] | None = None` 不變
- [x] 3.2 同檔案的 EpisodeRef 不動（已含 episode_id / title / published_at / guests / ai_summary）

## 4. Answer prompt grounding block（落實 `Chat endpoint answers with citations using Tier 2 RAG` MODIFIED 的 grounding block 行為）

- [x] 4.1 修改 `backend/app/services/llm_prompts.py` `render_answer_prompt` 落實 `Chat endpoint answers with citations using Tier 2 RAG` MODIFIED：新增 `enumeration_block: str | None = None` 參數；非 None 時 prepend 在 chunks block 之前
- [x] 4.2 新增 `format_enumeration_block(episodes: list[EpisodeRef], total: int, fallback_marker: str) -> str` helper：產生 spec example 那個格式（`## 相關集數清單（共 N 集）` header + 編號列表 + 截斷 30 集時 header 改成「共 N 集，以下列出最新 30 集」+ fallback_marker == "guest_only" 時 header 改成「⚠ 沒有完全相符的集數...」+ 0 集時 header 為「## 沒有找到相符的集數」）。建議放 `backend/app/services/episode_finders.py` 或 `llm_prompts.py` 內部
- [x] 4.3 修改 `backend/app/services/rag.py` `answer_with_chunks`：新增 keyword-only param `enumeration_block: str | None = None`；傳遞給 `render_answer_prompt`
- [x] 4.4 修改 `backend/app/api/query.py` chat handler：取得 enumeration 結果後呼叫 `format_enumeration_block` 產出 prompt 字串，傳入 `answer_with_chunks(..., enumeration_block=...)`

## 5. 前端 EnumerationSection 漸進顯示（落實 user-facing「預設 10 集、stepwise +10」UX，per design Decision 6）

- [x] 5.1 修改 `src/QueryPage.jsx` `EnumerationSection` 元件：新增 `displayCount` state 預設 10；改 `episodes.slice(0, displayCount)` 渲染；header 從「相關集數（N）」改為「相關集數（共 N 集）」
- [x] 5.2 加「再顯示 10 集（共 N 集）」按鈕：當 `displayCount < episodes.length` 時 render，點擊 `setDisplayCount(c => c + 10)`
- [x] 5.3 全部顯示完按鈕：當 `displayCount >= episodes.length` 時按鈕變「已全部列出（共 N 集）」disabled
- [x] 5.4 空結果處理：當 `enumeration_episodes` 為 empty list（非 null），顯示 section 含「沒有完全相符的集數」訊息；null 時 section 完全不渲染（與現有行為一致）
- [x] 5.5 雙語：所有新文案加 zh + en（再顯示 10 集 / Show 10 more；共 N 集 / N episodes total；已全部列出 / All listed；沒有完全相符的集數 / No matching episodes）

## 6. 整合測試（grounding + AND fallback + 空結果）

- [x] 6.1 新增 `backend/tests/test_chat_enum_grounding.py`：(a) `test_grounding_block_structured_format`（fixture 2 episodes → assert 輸出含 spec example 那段文字 byte-equal 比對）；(b) `test_grounding_block_truncates_at_30`（fixture 50 episodes → assert 只列前 30 + header 含「共 50 集，以下列出最新 30 集」）；(c) `test_grounding_block_guest_only_fallback_header`（fallback_marker="guest_only" → assert header 含「⚠ 沒有完全相符的集數」）；(d) `test_grounding_block_empty_result`（episodes=[] → assert header 為「## 沒有找到相符的集數」）
- [x] 6.2 新增 `backend/tests/test_compute_enumeration_combiner.py`：(a) `test_topic_only_triggers_enum`（entities.topics=["歌單"]，guests/date 都空，rule pattern 不符 → assert find_by_topic 被叫到）；(b) `test_guest_and_topic_intersect`（mock find_by_guest 回 [EP143]，find_by_topic 回 [EP143, EP140] → assert combiner 回 [EP143]）；(c) `test_guest_topic_intersection_empty_falls_back_to_guest_only`（mock 交集 0 → assert 回 guest-only 結果 + fallback_marker="guest_only"）；(d) `test_rule_pattern_uses_question_topic_terms`（entities 全空、question="歌單那幾集" → assert extract_topic_terms_from_question 被叫 → 結果經 stopword filter 後傳入 find_by_topic）

## 7. Prod 驗證（落實 `Topic-only query triggers enumeration` + `Guest filter narrows retrieval AND grounds answer` + `Empty filter result keeps fields populated` 三個 scenarios）

- [x] 7.1 commit + push（commit message 列三件改動 + 對應 spec scenarios）；等 Zeabur frontend + backend build 綠
- [x] 7.2 chrome-devtools-mcp 自動化跑 4 個 query：(a) `"楊大正是哪幾集的來賓？"` → assert chat 文字含「2 集」（不再說「1 集」）+ enumeration_total=2；(b) `"歌單那幾集"` → assert enumeration_episodes 非空且非全 164 集 + enumeration_total < 50；(c) `"林志炫上過哪幾集"`（假設沒這個 guest）→ assert enumeration_episodes=[] + enumeration_total=0 + chat 文字明說沒找到；(d) `"馬世芳那幾集講過烤肉"`（AND 應該空）→ assert fallback to guest-only + grounding header 含「⚠」
- [x] 7.3 跑 R1.2 eval baseline（n=30，prod backend）：對比 R3.3 baseline `Episode Set Recall (enumeration, n=2) = 0.2067`；預期 q25（歌單）episode_set_recall 從 0.08 → 0.4+，q26（高雄美食）從 0.333 → 0.5+。落差大或反向退步代表 topic-filter SQL 召回有問題要 tune
- [x] 7.4 user 人工複測 SOP：注音輸入「歌單那幾集」「楊大正哪幾集」「馬世芳那幾集講過烤肉」三題 → 驗 chat 文字數字與卡片 N 一致 + stepwise「再顯示 10 集」按鈕動作正確

## 8. 收尾

- [x] 8.1 寫 release log entry（v1.7 內，date 2026-05-17 或實際 ship 日，slug `r3-3-chat-enum-grounding`，tag `enhancement`，user-perspective 講「現在問『歌單哪幾集』、『馬世芳上過哪幾集』，AI 答案會與下方卡片數字一致 + topic-only 也能列出相關集數 + 列太多時手機自動分批顯示」）
- [x] 8.2 更新 `docs/case-studies/r33-metadata-filter.md`（append Stage 8 — chat-enum-grounding 結果）+ prod eval 數字對比
- [x] 8.3 更新 `docs/roadmap.md` R3.3 row（加註 `r3-3-chat-enum-grounding` follow-up 已 ship、known limits A/B/C 解決）
- [x] 8.4 同步 memory `project_pending_followups.md`（issue #1 標完成）
- [x] 8.5 `/spectra-archive r3-3-chat-enum-grounding`
