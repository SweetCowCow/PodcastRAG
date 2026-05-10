## Context

R2.1 是 RAG 答案信任度建設的第一階段。R3.1 上線後 retrieval 從 2.4% 升到 23.8% Recall@5，使用者實際看到的答案開始有真材實料；但 R1.2 evaluation mini-set 上 Faithfulness（GEval）後段題型仍弱（cross-episode aggregation 8/10 score=1）— 答案有時與 retrieval 結果脫鉤、編造未出現的事實、不擅長拒答。同時前端 SourceCard 目前只顯示 chunk 主文，使用者沒辦法知道：(1) 命中片段附近講了什麼（before/after 上下文）；(2) 答案某句具體出自哪一個 source；(3) 怎麼跳到逐字稿那段確認原話。

當前 stack：
- Retrieval：pgvector + jieba/tsvector RRF（純 SQL，commit `de2dfd1`）
- Search response：list of sources，每個含 chunk_id / episode_id / title / start_time / end_time / text
- LLM answer：透過 Zeabur AI Hub `gpt-4o`（registered in `ai_steps.answer`）；prompt 在 `backend/app/services/llm_prompts.py`
- Frontend：QueryPage 使用 `<SourceCard>`（在 Shared.jsx）；TranscriptPage 已存在但無 deep-link 接收能力
- Eval：R1.2 framework 就緒，judge=gpt-5-nano（manual lock），mini-set 40 題 + sentinel 10 題

設計受 freemium 限制：匿名 search endpoint 也要回新欄位（不藏在登入牆後），LockedAnswerCard 才是 paywall。

## Goals / Non-Goals

### Goals

- Source response 加 `before_text` / `after_text` / `highlights` / `ai_summary_excerpt` 四欄位，涵蓋匿名與登入兩條 endpoint。
- LLM answer prompt 強制 citation 規範 + faithfulness + 拒答邏輯。
- 後端解析 LLM 回應、strip 無效 ref、保證即使 LLM 沒按格式答 UI 仍可降級顯示完整 sources。
- 前端 SourceCard 升級：渲染 `<mark>` 高亮、上下文文字、AI 摘要截斷+展開、跳到逐字稿 button。
- TranscriptPage 接收 `?t=<秒>` 自動 scroll + 高亮。
- archive gate：R1.2 mini-set Faithfulness 持平或上升。

### Non-Goals

- Inline `[1] [2]` numbered citation rendering 與答案句子 ↔ source hover 互動：R2.2 polish。
- few-shot examples in prompt：先觀察 R2.1 純規範版 Faithfulness 表現再決定。
- Stream output 與 inline ref 相容性處理：R2.2 才處理 inline。
- Redis cache 整合（R4 範圍）：但 R2.1 必須在 case study 註記 sources schema version，方便 R4 對齊 cache invalidation。
- TranscriptPage 反向回到 query 結果的導覽 UI：browser back 可達成。
- Mobile bottom sheet / 無障礙 ARIA 完整化：R2.2。
- citation_match_rate dashboard：R1.3 範圍。

## Decisions

### Decision 1: before/after_text 採前後各 2 個 segment 的 text 拼接

**選項**：
- A. 前後各 1 segment（~3-10s 上下文）
- B. **前後各 2 segment（chosen）**
- C. Time window ±30 秒（多個 segment 拼接）
- D. ±100 字截斷

**選 B 理由**：R3.1 chunk 已是 30-60s / 5-10 segments；前後各 2 segment 提供約 6-20 秒上下文，足以呈現「上一句說 / 下一句接」場景，又不會太長。SQL 用 `start_time < anchor.start_time` ORDER BY 取最近 2 row 即可，無需 window function 複雜化。Cross-chunk 的話前後 segment 跨越 chunk 邊界也沒問題（SourceCard 顯示為「…前句…[hit]…後句…」，使用者要更多上下文點 deep-link 進逐字稿）。

### Decision 2: highlights 用 PostgreSQL ts_headline()

**選項**：
- A. 前端 query 字串 full-text match
- B. 前端用 jieba 分詞後逐詞高亮
- C. **後端 ts_headline() 直接產 `<mark>` 標記（chosen）**

**選 C 理由**：R3.1 的 BM25 已用 `to_tsvector('zh', col)` + jieba parser；同一 tsvector 可直接餵給 `ts_headline()`，回傳的高亮片段保證與 retrieval ranking 用的 token 一致，避免前後端字串切法不同步。回傳格式 `… <mark>關鍵字</mark> 上下文 …` 前端直接渲染（用 dangerouslySetInnerHTML + 嚴格 sanitize）。前端不需要懂 jieba，純展示。Trade-off：每個 source 多一次 `ts_headline()` 呼叫，top-K=8 時 8 次同 row 的小查詢 — 效能可接受（PG 內建函式，~1-2ms each），實際以 EXPLAIN 量測為準。

### Decision 3: deep-link 採純秒數 URL（?t=252.6）+ 不自動播放

**選項**：
- A. **`?t=<秒>`（chosen，跟 YouTube 一致）**
- B. `?segment_id=<uuid>`（精確、不受 chunk 重切影響）
- C. 兩者都接

**選 A 理由**：當前 TranscriptPage 是純文字逐字稿介面、沒有播放器，所以 button 標籤是「跳到這段內容」（不是「跳到這段聽」）。秒數 URL 對使用者直觀、可分享、跟 YouTube / Apple Podcasts 慣例一致。Segment_id 雖精確但 R3.1 可能再切 chunk 時會有 segment_id 變動風險（雖實際上 transcript_segments 不會重切），秒數受 ASR 影響輕微（±0.5 秒誤差）容忍度高。Frontend 接到 `?t=252.6` 用 `Math.abs(seg.start_time - t) < 5` 判斷哪個 segment 算 hit、scroll 到該段。

### Decision 4: LLM citation 用 ref id 編號 + 後端嚴格 strip

**Prompt 新增**：把 sources 編號 `[1] [2] [3]...` 餵進 system prompt 的 `Sources` 區塊，要求 LLM 「每句完整事實在句尾標 `[ref id]`，沒有對應 source 的句子（譬如綜合多 source 推論）標 `[multi]`」。

**後端 citation_parser.py**：
- 解析答案文字中的 `[N]` 與 `[multi]`
- N 不在 1..len(sources) 範圍內 → strip 該 ref 但保留句子
- 全部 strip 後 reply 仍可讀（不會剩孤立括號）
- 解析結果存進 response.answer.citations: `[{sentence_idx, ref_ids[]}]`，給未來 R2.2 inline 渲染用

**降級邏輯**：若 LLM 完全不照格式（測試發現 ~5% 次數），response 仍回 sources 列表 + 純文字 answer；前端 SourceCard 仍可獨立呈現（不依賴 inline ref 完整度）。

### Decision 5: Faithfulness 退步即不合 archive

**Gate**：archive 前在 R1.2 mini-set 40 題上跑 prompt 改動前後對比。指標：
- Faithfulness（GEval）：必須 >= 改動前
- Answer Relevancy：必須 >= 改動前 - 0.05（容忍小幅下降，因強拒答可能略影響相關度評分）
- Recall@5：不變（prompt 不影響 retrieval）

若 Faithfulness 退步，propose 加 few-shot examples（屬 Non-Goals 中保留的選項）再跑一次。若仍退步則回滾 prompt 改動，僅保留 response shape + 前端 UI 部分入庫，prompt 留 R2.x 進一步研究。

### Decision 6: 雙語 UI 文字採內嵌 i18n key 模式

**現況**：`Shared.jsx` 已有 `lang === 'zh'` 三元判斷模式（`{lang === 'zh' ? '跳到這段內容' : 'Jump to transcript'}`）。

**選擇**：沿用現有模式，不引入 i18n library（i18next 等）。理由：(1) 規模還小（~10 條新文字）；(2) 不增加 build 依賴；(3) 維持 PodcastRAG 現有風格一致。R2.1 新增的雙語文字統一放在 SourceCard / TranscriptPage 的 component scope 內。

## Risks / Trade-offs

- **[ts_headline 效能風險]** → SQL EXPLAIN 量測 top-K=8 場景；如果 P95 > 100ms 增量，改用 client-side jieba highlight 作為 fallback
- **[LLM 不照 citation 格式]** → citation_parser 嚴格 strip，UI 不依賴 inline ref；R1.2 mini-set 量測「ref 標記合規率」當監控指標，<70% 才打回票
- **[Faithfulness 因強拒答下降使用者體感]** → archive gate 含 Answer Relevancy 容忍 0.05 緩衝；上線後若使用者 thumbs-down 升高、可在 R1.3 dashboard 看到趨勢、回滾 prompt
- **[deep-link `?t=` 在 chunk 邊界誤差]** → 用 ±5 秒 window 容忍；遠未命中時 fallback scroll 到頁首並 alert「未找到對應段落」
- **[匿名 search response 也回新欄位增加 payload size]** → 上下文 4 segment + highlights 每個 source 約 +500 bytes，top-K=8 約 +4KB；對 mobile 影響微小，可接受。R4 cache 後續再優化
- **[response shape 變更 breaks 現有 cache / client]** → 客戶端必須 graceful degrade，新欄位不在的 source 依舊可顯示；新加欄位都標 optional 在 spec 內
- **[stream output 與 ref 渲染衝突]** → R2.1 不渲染 inline ref，stream 影響不到本 change；R2.2 處理 stream 才需要設計 ref render order

## Migration Plan

R2.1 為純擴充：response 加欄位（向後相容）、prompt 改寫（archive gate 把關）、前端漸進升級。無需 DB schema migration。

部署順序：
1. **Backend 先**：response shape 變更 + citation_parser + prompt 改動 → 跑 R1.2 eval 對比 → 通過才繼續
2. **Frontend 後**：SourceCard + TranscriptPage 接 deep-link
3. **如失敗**：rollback git revert（response 加欄位的部分可保留，prompt 與前端 revert 即可）

不需 feature flag — 新欄位 backwards compat、prompt 改動有 eval gate 保護。

## Open Questions

- 是否要把 sources schema version 寫進 response top-level（譬如 `response.sources_schema_version: 1`）方便 R4 cache invalidation？建議寫進去，cost 微小、未來價值大。
- citation_parser 的 `[multi]` 標記要不要保留？或統一成 `[1,2,3]` 多 ref 格式更通用？建議改成 `[1,2]` 多 ref 格式（與學術論文慣例一致），prompt 同步調整。
- before/after 是否要 jieba 分詞 highlight？preliminary 決定不做（保留純文字），但若 R1.3 thumbs-down 數據顯示使用者期待，再考慮加。
