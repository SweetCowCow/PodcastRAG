## Why

R3.1 上線後 episode-level Recall@5 達 23.8%（10x baseline 2.4%），但 Recall@20 = 61.9% 顯示「答案的 episode 大多在 retrieval pool 裡，只是排不進前 5」。Case study (`docs/case-studies/r31-hybrid-retrieval-rollout.md`) 三個觀察驅動 R3.2：

1. **Description chunks 在 hybrid RRF 排序壓掉 transcript anchor**。q01 「節目名怎麼來的」EP1 description 排第 1（對的 episode），但 EP1 transcript 解釋段（@252.60）落在 rank 9-20。
2. **Podcast 段落噪音多**：intro / outro / 業配話術每集重複，BM25 對它們高分但對使用者無價值。
3. **跨 episode 競爭抹平 routing 訊號**：query 該去哪集找答案，跟 query 該排序哪個 chunk，是兩件事；目前混在一起。

R3.2 核心：**先選集再找段（two-layer retrieval）+ LLM 標每段語義角色（topic segmentation）**，並收齊 R3.1 case study 留下的微調項。

## Summary

兩層檢索：第一層用 episode description embedding 抓 top-10 集，第二層在那 10 集內跑現有 R3.1 hybrid retrieval。同時 LLM 對每個 transcript_segment 標 8 通用類別 + per-show 擴充類別，schema 留欄位但 R3.2 不做 retrieval 降權（先驗證標籤準度）。

## Motivation

R3.1 driver case：問題不是「檢索沒命中」，是「排序壓錯了優先級」。Two-layer 架構直接拆解「決定 episode」與「決定 chunk」這兩個目標。Topic segmentation 把 podcast 結構知識（intro/outro/業配重複話術 vs 主題討論）顯式化，未來支援更細的 retrieval 控制（譬如 admin 想搜「歌單環節」、想排除業配段）。

## Proposed Solution

### A. Two-layer retrieval

```
Query
  │
  ▼
[第一層 routing]  embed query → cosine vs episode_description_chunks.embedding → top-10 episode_id
  │
  ▼
[第二層 search]   在 top-10 episode 範圍內跑 R3.1 retrieve_hybrid (transcript + description chunks via RRF)
  │
  ▼
top-K=8 結果（per existing API）
```

修改點：
- `retrieve_hybrid()` 多接 `episode_id_filter: list[UUID] | None` 參數
- transcript / description CTE 的 WHERE 加 `episode_id IN :filter`
- 新 `route_episodes(db, show_id, query_embedding, k=10)` 函式做第一層
- query.py endpoint 先 route 再 search

Description top-K cap 改 3/8（R3.1 carry-over），但 two-layer 後可能不必再 cap，先保留再依 eval 結果調。

### B. Topic segmentation

LLM (gpt-4o-mini) 對每集 transcript 跑一次，per-segment 分類 8 通用類別（單選）：

| 類別 | 描述 |
|---|---|
| `intro` | 片頭歡迎、節目名介紹、本集主題提示 |
| `outro` | 結尾感謝、下集預告 |
| `sponsor` | 業配、優惠碼、廠商合作 |
| `topic_main` | 主題核心討論 |
| `anecdote` | 個人故事 / 插科打諢 / 題外話 |
| `guest_intro` | 來賓介紹、背景說明 |
| `factual` | 具體資訊（時間、地點、價錢、人名） |
| `meta` | 節目本身的話（譬如「這是第 100 集」「我們之前講過」） |

Per-show 擴充：`shows.segment_categories JSONB` 留 array of `{name, desc}`。LLM prompt 動態組裝（通用 ∪ show-specific）。R3.2 預先填「這又沒有很屌」的 `playlist_segment`（介紹歌曲、歌單環節）+ `live_performance`（來賓現場演唱）。

Schema:
- `transcript_segments.topic_label VARCHAR(50) NULL` (new column)
- `shows.segment_categories JSONB NOT NULL DEFAULT '[]'` (new column)

**不做 retrieval 降權**：R3.2 只標籤，不調整 RRF score。等 admin 抽 50 段審核 LLM 準度後，下一輪迭代決定 multiplier。

### C. R3.1 carry-over 收尾

1. **Eval runner `--metric-level` flag**：值為 `episode | chunk`（預設 `episode`）。episode 模式比對 retrieved episode_id 是否在 anchor episode_id 集合內。修 R3.1 case study 點出的 chunk-level metric 不公平懲罰 description hits 問題。
2. **Tokenizer dict `is_show_name` flag**：`tokenizer_custom_terms.is_show_name BOOLEAN NOT NULL DEFAULT false`。`_build_ts_query()` query 端剔除這類 token（不丟進 lexical query；embedding 那邊不影響）。R3.2 backfill 時把「這又沒有很屌」「大嘻哈時代」等已知節目名 flag 起來。
3. **拿掉 jieba 1-char filter**：R3.1 v3/v4 eval 證明對 episode-level recall 完全無影響，移除以簡化 code（保留 ≥2-char 條件）。

### D. Audit / 抽樣

新 admin endpoint `GET /admin/topic-seg/audit-sample?n=50`：隨機抽 50 個已標記 segment（含上下文 + LLM 標的 label + 該集 episode_id），admin UI 列表呈現給人工確認 LLM 標籤是否合理。R3.2 範圍只做 endpoint + 列表頁面，**不做修改 / 重標機制**（那是 R3.x 後事）。

## Non-Goals

- 業配/intro 段 retrieval 降權（multiplier）— R3.2 只標籤，下一輪迭代再做
- AI 自動建議擴充類別 — R3.x 候選
- 後台編輯 `shows.segment_categories` UI — R3.x，R3.2 只用 SQL 直接寫死
- 使用者介面用 segment 標籤篩選 — R3.x，可能跟列舉型查詢一起做
- 列舉型查詢支援（「哪些集有歌單？」）— 需要 metadata + SQL filter 不同架構，R3.3 範圍
- Topic seg per-segment 多標籤（multi-label）— 維持單選簡化
- dataset anchor 重打為 segment_id-level — 用 `--metric-level=episode` 規避
- tokenizer dict `weight_in_lexical_query` 數值欄位通用化 — 先 `is_show_name` 布林，未來視需求升級

## Alternatives Considered

- **Joint reweighting (R3.1 v5/v6 沿伸)**：在 retrieve_hybrid merge 處給 description rrf_score × 0.5。優點實作小，但無法解決 q01 那種 routing 跨 episode 噪音問題；只是壓制 description，treats symptom not cause。
- **第一層用 BM25 + RRF（不只 embedding）**：description 短（< 1000 token），語意 embed routing 已夠準，多加 BM25 增加複雜度但收益有限。entity-only query fallback 改寫為「不做 routing，直接全集 hybrid」即可。
- **LLM topic seg 用 gpt-4o**：~$35 全 show，沒必要那麼貴；gpt-4o-mini 在 8 類粗粒度分類足夠。
- **Multi-label per segment**：維運複雜（schema、prompt 失準），R3.2 先單選。
- **跑全 show 跑 LLM topic seg 改 chunk-level**：chunk 邊界 R3.1 才剛改，segment 邊界穩定，標 segment level 更耐 chunk 邏輯變動。

## Capabilities

### New Capabilities

- `topic-segmentation`: per-segment LLM 分類管線（schema 欄位 / LLM prompt 組裝 / backfill script / admin audit endpoint）

### Modified Capabilities

- `rag-query`: `retrieve_hybrid()` 加 episode_id 過濾參數；新增第一層 `route_episodes()`；endpoint 改先 route 再 search。Description top-K cap=3。eval runner 加 `--metric-level` flag。
- `db-schema`: `transcript_segments` 加 `topic_label` 欄；`shows` 加 `segment_categories JSONB`。
- `tokenizer-dictionary`: `tokenizer_custom_terms` 加 `is_show_name` 欄；`_build_ts_query` 過濾 show-name token。

## Impact

- Affected specs: `rag-query` (modified), `db-schema` (modified), `tokenizer-dictionary` (modified), `topic-segmentation` (new)
- Affected code:
  - New:
    - backend/app/services/topic_segmentation.py — LLM 標註 pipeline 服務
    - backend/app/api/admin/topic_seg.py — audit-sample endpoint
    - backend/app/schemas/topic_seg.py — request/response schemas
    - backend/scripts/backfill_topic_labels.py — 全 show 一次性 backfill
    - backend/alembic/versions/<rev>_r32_topic_seg.py — schema migration
    - backend/tests/test_route_episodes.py — 第一層 routing 測試
    - backend/tests/test_topic_segmentation.py — LLM 分類 pipeline 測試
    - backend/tests/test_tokenizer_show_name_filter.py — show_name flag 過濾測試
    - backend/tests/test_eval_metric_level.py — runner --metric-level 行為測試
    - backend/tests/test_admin_topic_seg.py — audit endpoint 測試
    - src/AdminTopicSegAuditTab.jsx — admin 抽樣審核頁面
  - Modified:
    - backend/app/services/rag.py — `retrieve_hybrid()` 加 episode_id_filter；新增 `route_episodes()`；description top-K cap=3
    - backend/app/services/tokenizer.py — `_build_ts_query()` 排除 is_show_name=true 的 token；移除 1-char filter
    - backend/app/api/query.py — endpoint 先 route_episodes 再 retrieve_hybrid
    - backend/app/models/transcript_segment.py — 加 topic_label 欄
    - backend/app/models/show.py — 加 segment_categories 欄
    - backend/app/models/tokenizer_term.py — 加 is_show_name 欄
    - backend/app/api/admin/__init__.py — 註冊 topic_seg router
    - backend/app/api/admin/tokenizer.py — TokenizerTermCreate 加 is_show_name 選擇
    - backend/eval/runners/run.py — `--metric-level` flag 與 episode-level 比對邏輯
    - src/AdminPage.jsx — 加 admin-topic-seg-audit 路由
    - src/Shared.jsx — 側邊欄加入「分類審核」項
    - index.html — 引入 AdminTopicSegAuditTab.jsx
  - Removed: (none)
