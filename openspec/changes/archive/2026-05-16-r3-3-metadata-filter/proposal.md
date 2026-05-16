## Why

R3.2 兩層檢索 + topic seg 把 episode-level Recall@5 從 R1.2 baseline 2.4% 拉到 ~24%（R3.1 數字），但仍有兩類查詢系統處理不好：

1. **列舉題型**：「馬世芳上過哪幾集？」「2024 那集是哪集？」— RAG top-K 回 K 個 chunk 永遠處理不好集合答案
2. **抽象時間 / entity 別名**：「去年那集」、「疫情那段他講的」、「馬芳上次提到」— 純語意檢索抓不準時間 / 別名匹配

R3.3 透過 metadata filter（guests / date / topic hard filter）+ 多欄位 BM25 加權 + cross-episode 列舉支援，補完這兩塊缺口，預計 episode-level Recall@5 對比 R3.2 baseline 拉升 5-10pp。

## What Changes

- **新增 episodes.guests JSONB 欄位** — 來賓清單，list of strings
- **RSS title regex 抽 guests** — `Ft.|Feat.|feat.|featuring|【ft.xxx】` pattern，新集即時 + 一次性 backfill ~400 集
- **Admin Guests 編輯 UI** — admin 可逐集修改 guests（修錯抽、補別名如 馬芳=馬世芳）
- **LLM query entity extractor 服務** — 新增 `app/services/query_entity.py`，單一 LLM call 抽 `{date_range, guests, topics}` JSON，fail-open 設計（LLM 失敗退回不 filter，不回錯）
- **Admin AI Step 新增 `entity_extraction`** — admin 可切 model 不用 redeploy；bake-off gpt-4o-mini / gemini-2.5-flash-lite / claude-haiku-4-5
- **新增 episodes.title_tsvector generated column** — jieba tokenized，title 進 BM25 lexical pool
- **rag-query SQL 重構為三欄位 BM25 加權** — title × 3.0 + description × 2.0 + chunk × 1.0，per-query rank summation（不動 setweight bitmap）併入既有 RRF
- **chat 回應 schema 加 `enumeration_episodes` 欄位** — 列舉題型回所有匹配 episodes，不只 top-K chunk
- **前端 cross-episode 列舉 UI** — 列舉題顯示集數列表 + 「跳到這集」button
- **Eval target**：跑 R1.2 dataset 對比 R3.2 baseline，episode-level Recall@5 +5-10pp

## Non-Goals

- **跨節目（cross-show）retrieval**：永久排除。產品 base 是 per-show（先選節目再問），跨節目搜尋是另一個產品形態
- **Speaker labels（誰講的）**：要重轉 360+ 集成本太高，留 P2 等真有需求再說
- **完全捨棄 rule-based date 抽取**：LLM entity extractor 走主路徑，但保留 prompt 中的 date pattern 規範讓 LLM 對齊；不在 R3.3 維護獨立 rule-based fallback impl（fail-open 直接退到無 filter）
- **Guests 別名的自動 fuzzy match**：admin 手動補別名是 R3.3 範圍；LLM-based fuzzy resolver 留待後續觀察 query log 後再評估

## Capabilities

### New Capabilities

- `episode-guests-management`: 來賓欄位的儲存、RSS 抽取、admin 編輯、一次性 backfill
- `query-entity-extraction`: 使用者問句的 LLM entity 抽取服務（date_range / guests / topics），含 admin AI step 整合與 fail-open 行為

### Modified Capabilities

- `rag-query`: 三欄位 BM25 加權（title / description / chunk）併入 RRF；metadata hard filter（guests / date）；cross-episode 列舉題型回應
- `db-schema`: episodes 表新增 guests JSONB + title_tsvector generated column
- `admin-llm-step-config`: AI step 列表新增 entity_extraction 步驟
- `rss-feed`: `_parse_episode` 加 guests regex 抽取

## Impact

- Affected specs:
  - New: `episode-guests-management`、`query-entity-extraction`
  - Modified: `rag-query`、`db-schema`、`admin-llm-step-config`、`rss-feed`
- Affected code:
  - New:
    - backend/app/services/query_entity.py
    - backend/app/api/admin/episode_guests.py
    - backend/app/schemas/episode_guests.py
    - backend/scripts/backfill_guests.py
    - backend/alembic/versions/r33_episodes_guests_and_title_tsvector.py
    - backend/tests/test_query_entity.py
    - backend/tests/test_rss_guests_extraction.py
    - backend/tests/test_admin_episode_guests.py
    - backend/tests/test_rag_multi_column_bm25.py
    - src/AdminEpisodeGuestsTab.jsx
    - docs/case-studies/r33-metadata-filter.md
  - Modified:
    - backend/app/models/episode.py
    - backend/app/services/rss_parser.py
    - backend/app/services/rag.py
    - backend/app/services/ai_step_resolver.py
    - backend/app/api/query.py
    - backend/app/schemas/query.py
    - backend/app/api/admin/__init__.py
    - src/AdminPage.jsx
    - src/QueryPage.jsx
    - src/Shared.jsx
