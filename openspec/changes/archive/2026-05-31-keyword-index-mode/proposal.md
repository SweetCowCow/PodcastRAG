## Why

現有 `POST /shows/{show_id}/search` 屬於語意搜尋（embedding + RRF），對於精準名詞、人名、Hashtag 這類「逐字命中」需求表現不穩；使用者反映想要明確的「索引模式」可以強制 AND 多關鍵字並在同一段、同一集內精準命中。UI redesign 已拍版三模式（索引／語意／對話），需要對應後端能力與結果頁規格才能上線索引 tab。

## What Changes

- 新增「索引模式（keyword）」後端 endpoint：對單一 show 做嚴格 AND 關鍵字搜尋，回三段式 sectioned 結果（T1 chunk-AND、T2 episode-AND 跨三池、T3 OR fallback）。
- SQL 一次 CTE 拿 T1 + T2，T1+T2 都 0 才觸發 T3 fallback；每 section LIMIT 100 並支援 incremental paginate。
- 跨池 episode 命中（T2）union 三池：`episodes.title_tsvector`、`episode_description_chunks.text_tsvector`、`transcript_chunks.text_tsvector`；每個關鍵字至少於某一池命中即視為該集命中該字，全字皆命中才入選。
- T1 高於 admin-tunable threshold（預設 10）時，T2 自動 collapse 為「+N 集亦有命中」chip。
- 查詢字串前處理：jieba 切詞 + 去除標點，**取消 AND/OR toggle 與引號 phrase 語法**（永遠 AND，OR 僅作 fallback）。
- 新增 admin 設定鍵：`keyword_t2_collapse_threshold`（int，預設 10）。
- 前端 `src/QueryPage.jsx` 索引 tab 串接新 endpoint，渲染三 section（V/W/Y）：
  - T1 chunk card：兩色（橘 / 青）輪替高亮命中詞、預設顯示命中前後一句、「上下 5 段」原地展開、跳播 btn。
  - T2 episode card：三池命中分佈計數 + inline「展開查看各段」。
  - T3 fallback：縮小版 chunk cards + 顯眼 mode-switcher chip + 警告文案。
- Section 內「顯示更多 5 段/集」incremental paginate，硬上限 100。
- 結果頁底永遠顯示 mode switcher chip；0 結果頁面同樣提供 chip + 範例查詢建議。

## Non-Goals

- 不動 HomePage、對話 source、Lock card、sticky audio player、paragraph 1.5 秒聚合、語意 mode Hybrid C 渲染 — 屬於並行 change `landing-and-mode-orchestration-redesign`。
- 不動 QueryPage 三 tab shell 與 tab 切換字串（Change 1 已 cover）。
- 不重做語意 endpoint `POST /shows/{show_id}/search` 的既有行為；本 change 新增另一支 endpoint，不取代。
- 不引入新的「檢索用」索引或重 schema migration（重用既有 tsvector 欄位與 jieba tokenizer）。**例外**：admin 可調 threshold 需在 `app_settings`（結構化單列表）加一個 `keyword_t2_collapse_threshold INT` 欄位 + 一支單欄位 alembic migration — 這是設定欄位、非檢索索引，與此 non-goal 精神不衝突（2026-05-31 ingest 校正）。
- 不做付費／quota gating（索引模式不打 LLM，沿用既有 ip-rate-limit）。

## Capabilities

### New Capabilities

- `keyword-search-mode`: 索引（keyword）搜尋模式的後端 endpoint、CTE/SQL 行為、三池 union 規則、T1/T2/T3 sectioning、collapse threshold 與 admin 設定。
- `keyword-search-results-ui`: QueryPage 索引 tab 結果頁的 sectioned 渲染、兩色高亮、incremental paginate、mode switcher chip 與 0 結果處理。

### Modified Capabilities

（無 — 重用既有 tokenizer dictionary、episode description index、rag-query 的 tsvector 欄位但不改變其既有 spec）

## Impact

- Affected specs:
  - New: `openspec/specs/keyword-search-mode/spec.md`
  - New: `openspec/specs/keyword-search-results-ui/spec.md`
- Affected code:
  - New:
    - `backend/app/api/keyword_search.py`（新 router）
    - `backend/app/services/keyword_search.py`（CTE 組裝 + 三池 union + jieba 前處理）
    - `backend/app/schemas/keyword_search.py`（request / response schema）
    - `src/KeywordResults.jsx`（T1/T2/T3 section 元件 + 高亮 helper）
  - Modified:
    - `backend/app/main.py`（掛新 router）
    - `backend/app/models/app_settings.py` + `backend/app/schemas/settings.py`（新增 `keyword_t2_collapse_threshold` 結構化欄位；既有 `backend/app/api/settings.py` 的 GET/PUT 自動涵蓋）
    - `src/QueryPage.jsx`（索引 tab：現為「即將推出」placeholder `QueryPage.jsx:490`，改為接 endpoint 與渲染 `<KeywordResults>`，並傳 `onSwitchMode` wire 到既有 `setActiveTab`）
    - `src/Shared.jsx`（如需新增 highlight / chip 共用元件）
  - New (migration):
    - 一支單欄位 alembic migration：`app_settings` 加 `keyword_t2_collapse_threshold INT NOT NULL DEFAULT 10`
  - Removed: 無
