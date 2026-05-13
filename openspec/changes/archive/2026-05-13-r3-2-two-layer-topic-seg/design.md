## Context

R3.1 hybrid retrieval（jieba + tsvector + RSS description index + RRF）已上線（commit `de2dfd1`），prod 累積：
- 354 transcripts、98,291 transcript_chunks（100% 有 text_tsvector + embedding）、556 episode_description_chunks
- 29 個 manual seed jieba dict 詞、3 shows / 162 episodes（這又沒有很屌、曼報、新聞挖挖哇）
- R1.2 eval：episode-level Recall@5 = 23.8%，Recall@20 = 61.9%
- R3.1 case study: `docs/case-studies/r31-hybrid-retrieval-rollout.md`

R3.2 仍在 R3.1 的 SQL-only 戰線（不引 LlamaIndex / LangChain），不重轉錄、不改 chunk 邊界。

Constraints：
- LLM topic seg 全 show 一次性 backfill 預算 ≤ $5（gpt-4o-mini ~$0.01/集 × 354 = ~$3.5）
- 不增加新 cost-recurring service（不上 GPU、不改 VPS）
- Eval metric 變動須維持跟 R1.2 / R3.1 數字可對比性（透過 `--metric-level` flag 控制）
- Description top-K cap 改動需要 backward compatible（API shape 不變）

## Goals / Non-Goals

### Goals
- **Episode-level Recall@5 從 R3.1 的 23.8% → 目標 ≥ 35%**（two-layer 把對的 episode 從 rank 9-20 拉到 top 5）
- 移除 R3.1 case study 揭示的 description-vs-transcript 排序壓制問題
- 為未來 retrieval 細粒度控制（業配降權、segment 篩選）打下基礎（schema + 標籤）
- 收齊 R3.1 case study 的三個 carry-over 微調項

### Non-Goals
- 業配 / intro 段 retrieval 降權 multiplier（R3.2 後續迭代）
- AI 自動建議擴充類別（R3.x）
- 後台編輯 segment_categories UI（R3.x）
- 列舉型查詢支援（R3.3 / new change）
- segment 多標籤（multi-label）
- dataset anchor 重打為 segment_id containment

## Decisions

### Decision 1: Two-layer = gate-and-rank（不是 joint reweighting）

**選擇**：
- 第一層 `route_episodes(db, show_id, query_embedding, k=10)`：純語意排名，回 list[UUID] of top-10 episode_id
- 第二層 `retrieve_hybrid(db, show_id, query_embedding, question, episode_id_filter=routed_eps, k=8)`：在 routed_eps 範圍內跑 R3.1 hybrid retrieval

**Why**：
- R3.1 case study 證明 description chunks 在 RRF 排序壓 transcript chunks（q01 EP1 description 排 1，但 EP1 transcript anchor 落 9-20）
- Joint reweighting（譬如 description rrf_score × 0.5）只壓低 description，不解決「跨 episode 噪音」根因
- Gate-and-rank 顯式拆解「決定 episode」與「決定 chunk」兩目標

**Alternatives**：
- Joint reweighting：簡單但治標不治本
- 三層（episode → topic → chunk）：R3.2 還沒做 topic 標籤的 retrieval 降權；多一層複雜度收益小

### Decision 2: 第一層 routing K=10、純 embedding（不混 BM25）

**選擇**：top-10 episode；只用 description embedding 對 query embedding 做 cosine 排名。

**Why**：
- 162 集中圈 10 集約 6%，留足夠 buffer；K=5 對 routing 失誤敏感
- description 只幾百字，embedding routing 夠準；混 BM25 增加複雜度收益有限
- entity-only query（譬如使用者打「迪拉胖」三個字）embedding 對短詞處理弱 → 設 fallback：query 字數 < 4 chars 時略過 routing，直接走全集 hybrid

**Alternatives**：
- K=5：精準但失誤代價高
- K=20：失去 routing 意義，跟全集差不多
- 混 BM25：description 段太短，BM25 訊號弱

### Decision 3: Topic seg 用 gpt-4o-mini，per-segment 單選 8 通用類別 + per-show 擴充

**選擇**：
- 全集 transcript（segments 連起來 ~10K-30K tokens）一次餵 gpt-4o-mini，要求 JSON 輸出 per-segment label
- 通用 8 類：`intro / outro / sponsor / topic_main / anecdote / guest_intro / factual / meta`
- Per-show 擴充：`shows.segment_categories JSONB` array of `{name, desc}`，prompt 動態組裝（通用 ∪ show-specific）

**Why**：
- gpt-4o-mini 8 類粗粒度約 80% 準（內部評估），全 show ~$3.5 一次性可承受
- segment 邊界穩定（不像 chunk），未來改 chunk 邏輯不破壞
- per-show 擴充支援節目特性（這又沒有很屌的歌單環節 / 曼報的公司介紹）

**Alternatives**：
- gpt-4o：~$35 全 show，沒必要
- 多標籤（multi-label）：準度降到 65-70%，schema 變 JSONB array
- chunk-level 標籤：跟 chunk 邊界耦合
- haiku-4-5：$0.005/集更便宜，但中文 corner case 多

### Decision 4: R3.2 預先填「這又沒有很屌」的擴充類別（手動 SQL）

**選擇**：R3.2 backfill 前手動 `UPDATE shows SET segment_categories = ... WHERE id = <這又沒有很屌>` 寫進兩個擴充類別：
- `playlist_segment`：介紹歌曲、歌單環節
- `live_performance`：來賓現場演唱

**Why**：
- LLM backfill ~$3.5 是一次性成本，沒填這次就要重跑
- 其他節目（曼報、新聞挖挖哇）未來 admin UI 上線後再補

### Decision 5: 標籤但不降權（R3.2 階段）

**選擇**：R3.2 backfill 寫 `transcript_segments.topic_label`，但 retrieval SQL 不依此調 ranking。

**Why**：
- LLM 標準度需先驗證（admin 抽 50 段審核）才有信心降權
- 若標歪卻降權，會誤殺真內容
- Schema 留欄位 + 標好 → 下一輪迭代直接加 multiplier 即可

### Decision 6: Description top-K cap = 3（R3.1 carry-over）

**選擇**：`retrieve_hybrid` merge 後限制 description hits 在 top-K 中最多 3 個。

**Why**：
- R3.1 q01 範例：top-5 全是 description，transcript anchor 完全沒出來
- Two-layer 後可能不必這麼嚴（routing 已限 episode），但保留 cap 為穩健機制

**Alternatives**：
- 不 cap：相信 two-layer 已解決問題，但 R3.1 v4 已驗證 ranking 偏好確實存在
- 完全不收 description：失去 description 命中能力

### Decision 7: Eval runner `--metric-level` flag，預設 episode

**選擇**：runner 加 `--metric-level {episode,chunk}`，預設 `episode`：
- `episode`：retrieved chunk 的 `episode_id` 在 anchor episode_id 集合內 → hit
- `chunk`：保留現有 `(episode_id, start_time // window_s)` bucket 比對（R1.2 / R3.1 行為）

**Why**：
- R3.1 case study 證明 chunk-level 對 description hits（start_time=0）系統性誤判
- 改預設 episode 讓 R3.2 / R3.3 metric 正確反映改進
- `chunk` 模式保留作為「精確時間點」評估，將來 R2 citation 改進可用

### Decision 8: Tokenizer dict `is_show_name` flag（R3.1 carry-over）

**選擇**：
- `tokenizer_custom_terms.is_show_name BOOLEAN NOT NULL DEFAULT false`
- `_build_ts_query()` 從 jieba tokens 過濾 `is_show_name=true` 的詞（不丟進 lexical query；embedding 不影響）
- R3.2 backfill UPDATE 把「這又沒有很屌」「大嘻哈時代」「異世界美食家」等已知節目名 / 大主題詞 flag 起來

**Why**：
- R3.1 case study：q01 「節目名怎麼來的」EP1 解釋段被 EP110「字面提到節目名 9 次」壓掉，因為 dict 把節目名認成單 token 後 BM25 對閒聊提及加分
- Boolean flag 簡單實作；未來如需更細粒度（譬如「嘻哈大賽」vs「大嘻哈時代」差別權重），升級成 `lexical_weight` 數值欄位

### Decision 9: 拿掉 jieba 1-char filter

**選擇**：`_build_ts_query` 移除 `if len(tok) < 2: continue` 條件。

**Why**：
- R3.1 v3/v4 eval：episode-level recall 在 keep 1-char vs drop 1-char 完全相同（v1=v3, v2=v4）
- 通用 1-char 詞（是、的、了）OR-join 後 ts_rank 已經能正確壓低權重
- 拿掉 = 簡化 code，少維護一條 special case

### Decision 10: Topic seg backfill 走 standalone script，不接 transcription pipeline

**選擇**：
- `backend/scripts/backfill_topic_labels.py --all / --episode-id <UUID>`
- LLM call 在 backfill script 直接走 sync OpenAI client（worker 不接，因為一次性）
- 失敗的集合 print 出來，可單集重跑

**Why**：
- 跟 R3.1 backfill 一致（rebuild_chunks / build_description_index）
- 未來新轉錄集數要自動 topic seg → 那是 R3.x（接到 transcription pipeline）

**Future**：transcribe_episode 完成後自動觸發 topic seg task — R3.x 範圍。

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| 第一層 routing 把對的 episode 排到 K+1 → 完全 miss | K=10 留 buffer；entity-only query fallback 略過 routing |
| LLM 標籤準度差 → 影響後續降權 | 抽 50 段 admin 審核 task 必做；不準時不上 multiplier |
| backfill 過程 prod 受影響 | topic_label 是 nullable 新欄；retrieval SQL 不依賴它 |
| description embedding 對短 query 訊號弱 | fallback 條件：query.strip() 字元 < 4 → 略過 routing |
| `is_show_name` flag 後 lexical query 為空 | 跟 R3.1 fallback 一致：lexical 為空時退化純 semantic |
| Per-show 擴充類別 LLM 標準度 | R3.2 backfill 後抽 50 段含 show-specific 類別審核 |
| Two-layer 後 latency 增加 | 第一層 1 次 vector query (~50ms)；可接受 |

## Migration Plan

**Stage 1（schema + service code）**：
- Alembic migration: `transcript_segments.topic_label`, `shows.segment_categories`, `tokenizer_custom_terms.is_show_name`
- 新增：`route_episodes()`, `topic_segmentation` service, audit endpoint, runner `--metric-level` flag
- 修改：`retrieve_hybrid()`, `_build_ts_query()` 移除 1-char filter + 加 show_name 過濾
- 全部 unit tests 通過

**Stage 2（部署 + 設定 carry-over）**：
- Push to prod，redeploy 4 service
- SQL UPDATE：「這又沒有很屌」`segment_categories` 寫入 playlist_segment + live_performance
- SQL UPDATE：標 dict 中已知節目名 `is_show_name=true`（譬如「這又沒有很屌」「大嘻哈時代」「異世界美食家」）

**Stage 3（topic seg backfill）**：
- 跑 `backfill_topic_labels.py --all`，估時 30-60 min（OpenAI rate limit + 354 集）
- 完成後 `transcript_segments.topic_label` ~ 100% 覆蓋

**Stage 4（eval 對照）**：
- 跑 R1.2 eval `--metric-level=episode`：
  - Pre-R3.2 baseline（R3.1 final）：episode-level Recall@5 = 23.8%
  - Post-R3.2：跑出來看
- 跑 admin audit endpoint，抽 50 段審核 LLM 標籤
- Release log v1.5 entry

**Rollback**：
- Service code rollback：revert commit；新欄位保留（ignored by old code）
- Schema rollback（極端）：drop 新欄位（會丟 backfill 結果，~$3.5 重做）

## Open Questions

1. 第一層 routing fallback 條件「query 字元 < 4」是否合適？或改用 jieba token 數 < 2？— 採後者（更精準）
2. Topic seg 對 segment 邊界很短的（< 5 秒，譬如 Whisper 切的填詞）怎麼標？— 跟前一個 segment 同 label，或全部標 `meta`；採前者
3. Audit endpoint 是否同時顯示前後 1-2 個 segment 上下文？— 是，列表呈現 `[prev_seg.text] [target_seg.text *with label*] [next_seg.text]` 三段對照

---

## 2026-05-13 archive follow-up — partial supersession by r3-5-disable-routing

本 change 兩個主軸：
1. **Topic segmentation backfill** — 全 corpus 跑完，topic 段 metadata 落盤；prod 用到的功能（segment_categories 等）保留。
2. **Two-layer routing (`route_episodes`)** — 被 r3-5-disable-routing **整層關掉**：純人類 query Recall@5 從 0.0625 → 0.4375（routing 是 net negative）。

archive 理由：
- Topic seg backfill 部分已完成且 in prod，**保留**
- Two-layer routing 部分 code 保留但 default 翻向 false（r3-5），未來若改 routing 為 hybrid（加 lexical 信號）才會考慮重新啟用
- 本 change 未做完的剩餘 11 tasks 多為 routing-side eval / cleanup，已不再相關

詳見 `r3-5-disable-routing` design.md D2（spike 證據）、D7（與本 change 的關係）。
