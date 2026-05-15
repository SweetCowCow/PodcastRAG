## Context

R3.x 系列 RAG 優化計畫第三段：

| 階段 | 已交付 / 規劃 | episode-level Recall@5 |
|---|---|---|
| R1.2 baseline | 純語意（pgvector）| 2.4% |
| R3.1 hybrid retrieval | jieba + RRF (semantic + BM25)，description 進 BM25 池 | 23.8% |
| R3.2 two-layer + topic seg | description embedding routing top-K=10 → 第二層 RRF；topic 標籤 backfill（離線跑中） | 預期 ≥ 35%（待 backfill 完成評測）|
| **R3.3 metadata filter（本案）** | guests / date hard filter + 多欄位 BM25 + cross-episode 列舉 | 目標 +5-10pp |

**現況**：

- `backend/app/services/rag.py` 已有 `retrieve_hybrid` (transcript chunks RRF) + `retrieve_descriptions` (description chunks RRF) + `route_episodes` (R3.2 第一層 routing)，兩個 RRF SQL 都有 `episode_filter` placeholder 給上層注入 hard filter
- `episodes` 表存 `title (varchar 500)` / `description (text)` / `published_at (datetime)` — 沒 guests 欄位、沒 title_tsvector
- RSS 進料中央漏斗 `rss_parser._parse_episode` 目前抽 title / description / published_at / audio_url，沒抽 guests
- Admin AI step config 已有 5 個固定步驟（answer / rewrite / summary / embedding / transcription），切 model 不用 redeploy；新增第六個 `entity_extraction` 是延伸
- chat path 在 `app/api/query.py:288-306`：rewrite → embed → routing → retrieve_hybrid → answer_with_chunks。entity 抽取要插在 rewrite 之後、retrieval 之前

**Stakeholders**：產品（podcast 主持人 / 聽眾）、後端（rag retrieval 路徑）、前端（QueryPage 列舉題型 UI）、admin（guests 編輯）。

## Goals / Non-Goals

**Goals**:

- Episode-level Recall@5 對比 R3.2 baseline 提升 5-10pp（用 R1.2 dataset 跑 `--metric-level=episode --skip-judge --top-k=5`）
- 列舉題型回應正確：`{enumeration_episodes: [...]}` 包含所有匹配 episode（不只 top-K chunks 抽出的 episode 集合）
- LLM entity extractor fail-open：LLM service 不可用 / 抽出 invalid JSON / 抽出 schema 不符欄位 → 退回不 filter，retrieval 照走完整路徑（不回 5xx）
- Guests 抽取對既有 ~400 集 + 未來新集數兩條路徑都涵蓋
- BM25 weighting 查詢時可調（不重 build vector）

**Non-Goals**:

- 跨 show retrieval（per-show 是產品 base）
- Speaker labels（重轉錄成本太高，留 P2）
- LLM-based 別名 fuzzy resolver（admin 手動補別名為主）
- 維護獨立 rule-based date extractor 作為 LLM fallback（fail-open 直接退無 filter）
- Guests 抽取的 LLM impl（先靠 RSS regex + admin 編輯，未來如 RSS title 不規範再升級）

## Decisions

### Decision 1：guests 雙路徑寫入 + admin UI 編輯

**選擇**：

1. RSS sync 時，`rss_parser._parse_episode` regex 抽 guests，寫入 `episodes.guests JSONB`（list of strings）
2. 一次性 `scripts/backfill_guests.py` 對既有 episodes 重新跑 regex 補欄位
3. `GET /admin/episodes/{id}/guests` + `PUT /admin/episodes/{id}/guests` endpoint
4. `AdminEpisodeGuestsTab.jsx` 列出單 show 全集數 + 內聯編輯 chip 介面

**Regex pattern**（提案）：

```python
GUESTS_REGEX = re.compile(
    r"(?:Ft\.|Feat\.|feat\.|featuring|【ft\.|【Ft\.|【feat\.)"
    r"\s*([^】|/、,，]+?)(?=【|】|\||/|、|,|，|$)",
    flags=re.IGNORECASE,
)
```

對 title 跑 `findall`，每個 match strip 後加入 list；list 去重保持原順序。空結果寫 `[]`（不寫 NULL，方便 SQL `@>` 操作）。

**Rationale**：RSS sync 已是中央漏斗，加 regex 成本低；admin UI 處理「節目主寫法不規範」的長尾（譬如「Ft. 馬世芳 vs 來賓：馬世芳」這類 regex 抓不到的）。雙路徑 + 手動編輯比單純走 LLM 抽便宜（每集 < $0.01 vs LLM 抽 $0.005-0.01 每集 × 持續累積）且更可控。

### Decision 2：LLM query entity extractor 走獨立 service + admin step

**選擇**：

- 新增 `app/services/query_entity.py`，公開 `async def extract_entities(client, model, question) -> QueryEntities`
- `QueryEntities` Pydantic model：`{date_range: tuple[datetime, datetime] | None, guests: list[str], topics: list[str]}`
- LLM call 用 `response_format={"type": "json_object"}` + JSON schema 驗證 + 1 次 retry，所有失敗路徑（exception / invalid JSON / schema 不符）→ log warning + 回 `QueryEntities(date_range=None, guests=[], topics=[])`（fail-open）
- 整合進 `query.py` chat path，在 rewrite 之後、routing 之前 call
- Admin AI step `entity_extraction` 新增 row，model 預設 gpt-4o-mini；admin UI 已有 step 切換（admin-llm-step-config archived）

**Prompt 設計**：

system prompt 列出抽取規則 + few-shot examples（覆蓋抽象時間「去年」「疫情那年」「最近這集」、entity 別名「馬芳」、純主題詞 query「裴社長那道菜」）。`date_range` 解析時固定「現在 = 系統時間」；相對日期換算用 prompt 內明確數值（避免 LLM 幻想日期計算）。

**Bake-off 流程**：

對 R1.2 dataset 的 48 題各跑三 model（gpt-4o-mini / gemini-2.5-flash-lite / claude-haiku-4-5），人工 audit 抽 10 題比對抽出 entity 正確度，最便宜且 entity F1 ≥ 0.7 者勝出。

**Rationale**：rule-based 在 podcast 場景有 80% pattern 涵蓋，但「抽象時間 + entity 別名」一定會來；先寫 rule-based 之後重構成 LLM 是兩倍工。Fail-open 而非 fail-closed 是因為 entity 抽取是錦上添花，retrieval 沒它仍能跑（recall 降但不破）。

### Decision 3：BM25 多欄位走「per-query rank summation」而非 setweight bitmap

**選擇**：

- 新增 `episodes.title_tsvector` 為 generated column，jieba tokenized（複用既有 `tokenize_for_tsvector` from R3.1）
- `_TRANSCRIPT_RRF_SQL` + `_DESC_RRF_SQL` 各自獨立保留；新增第三池 `title_lexical` SQL 對 `episodes.title_tsvector` 用 `to_tsquery + ts_rank`
- RRF 階段三池融合：`1/(k+rank_semantic) + 1/(k+rank_chunk_lexical) + 0.7×1/(k+rank_desc_lexical) + 0.5×1/(k+rank_title_lexical)`（chunk 1.0 / desc 0.7 / title 0.5 權重設定保留調整空間）
- 權重常數寫在 Python 端（`rag.RRF_WEIGHTS`），不寫死 SQL，方便日後 tune

**Rationale（為何不走 setweight bitmap）**：

- setweight 要在 build tsvector 階段標 weight（A/B/C/D），未來改 weight 要重 build vector；分查詢加總是查詢時組合
- R3.x 階段 R1.2 baseline 才剛上線，weight 一定常 tune（不同題型 / 不同 show 特性 / corpus 持續長都會驅動 tune）
- query 量現況每天幾百到幾千，三池 RRF 融合 latency 開銷（~30-40%）相對單一 ts_rank_cd 可接受

### Decision 4：cross-episode 列舉題型走「response shape 擴充」而非新 endpoint

**選擇**：

- `ChatResponse` 加新欄位 `enumeration_episodes: list[EpisodeRef] | None`
- `EpisodeRef = {episode_id, title, published_at, guests, ai_summary}`
- 觸發條件：entity extractor 抽出 `guests` 非空 OR `date_range` 非空 OR query 含「哪幾集 / 哪集 / 哪些集」rule pattern → 跑 `episodes` 表 hard filter SQL（`guests @> :guest` / `published_at BETWEEN :start AND :end`），列出全部匹配 episode（**不限** top-K）
- 同時保留現有 `citations` 路徑（chunk-level top-K）— 兩個一起回；前端依題型擇一顯示為主
- `enumeration_episodes` 沒匹配時回 None（不回 `[]`）

**Rationale**：列舉題不適合 top-K（答案集合大小未知），用 hard filter 全部回；但同時保留 citations 是因為使用者問「馬世芳上過哪幾集」可能也想看具體段落（chunks 從匹配 episode 內挑）。新 endpoint 會破壞前端現有路由邏輯，response shape 擴充對既有 client 是 additive。

### Decision 5：Eval 對照範圍

跑 R1.2 dataset（this-not-that-cool 48 題），`--metric-level=episode --skip-judge --top-k=5`，產出 R3.3 vs R3.2 對照表進 `docs/case-studies/r33-metadata-filter.md`。額外針對 5 題 cross-episode 列舉題（從 dataset 中挑或新增）測 `enumeration_episodes` precision / recall。

## Risks / Trade-offs

- **LLM entity extractor 增加每 chat query latency 500-1000ms** — chat 從 ~3s 變 ~4s。可接受，但要監控 P95；如果撞 5s 以上要考慮平行化（entity 抽取 + embedding 同步跑）
- **Fail-open 讓使用者誤以為 filter 沒生效** — 例如 LLM 抽錯 entity，回應卻沒任何 filter 訊息，使用者問「2024 那集」回到 2023 也被當答案。Mitigation：回應加 `applied_entities` 欄位（前端 dev 模式顯示），人工抽查；prod 不顯示避免使用者疑惑
- **Guests regex 漏抽長尾** — 中文 podcast title 寫法多元，regex 漏抽率預估 30-40%。Mitigation：admin UI 是補丁；長尾累積後再評估升級 LLM 抽
- **RRF 多一池對 latency 影響** — 三池融合比兩池多 ~30-40% retrieval 時間。Mitigation：RRF 各池 query SQL 已經是 `LIMIT :per_side`，title pool 的 `per_side` 設小一點（譬如 20，chunk 維持 100）；title corpus 比 chunk 小 100 倍，rank 算很快
- **schema migration 對 prod 影響** — `title_tsvector` generated column rebuild 全表（~400 列）一次完成，秒級完成；`guests JSONB` default `[]` 不卡 lock。低風險
- **R3.2 backfill 仍跑中** — 預估 ~10 小時完成。R3.3 開做時 backfill 應已結束；若 R3.3 進度比 backfill 快（不太可能），要避免動到 `transcript_segments.topic_label` 相關 SQL

## Migration Plan

1. **Phase 1（schema + RSS extractor）**：alembic migration 上 prod，RSS sync 開始抽新集 guests；既有集數 guests 仍為 NULL/[]
2. **Phase 2（backfill script）**：跑 `scripts/backfill_guests.py` 對 ~400 集回填，秒級完成
3. **Phase 3（admin UI）**：guests 編輯 endpoint + Tab 上線；admin 校對抽錯 / 補別名
4. **Phase 4（entity extractor + RRF SQL refactor）**：上線 entity_extraction step config，rag.py 改用三池 RRF；初期 RRF_WEIGHTS 用 design 預設值
5. **Phase 5（eval + case study）**：R1.2 dataset 跑 R3.3，對比 R3.2 寫進 case study；視結果調 RRF_WEIGHTS

## Open Questions

- entity extractor model bake-off 由 R3.3 內進行還是預先用 R1.2 judge bake-off 結論？（傾向 R3.3 內進行，因為 entity extraction prompt 跟 judge prompt 不同，model 行為可能不同）
- `enumeration_episodes` 觸發條件中的「query 含『哪幾集 / 哪集 / 哪些集』rule pattern」是否獨立寫？或完全靠 entity extractor 抽出 guests/date 自動觸發？（傾向獨立寫，因為「哪幾集講過 podcasting」這種純 topic 列舉不會被 entity 抽出，需要 rule pattern 補）
