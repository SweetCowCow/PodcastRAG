## Context

查詢頁三模式（索引／語意／對話）輸入框目前只有通用提示。既有 `src/TrendingQueriesChips.jsx` 打 `GET /shows/{id}/trending-queries`（7 日熱搜，`trending-queries-api` capability，門檻 COUNT≥3 才入榜）做引導，但冷啟動節目沒有足夠熱搜。需要 per-show-per-mode 的預產範例當 fallback。

可重用的既有機制：
- `episode-ai-summary`：轉錄完成後鏈式 enqueue Celery、map-reduce、idempotent、走 `ai_steps` 取 endpoint/model。
- `ai_steps`（`admin-llm-step-config`）：每個 AI 步驟的 provider/model 設定。
- `episodes.ai_summary` / `episodes.guests`（JSONB）/ topic terms：現成素材。

## Goals / Non-Goals

**Goals**
- 每節目 × 每模式有 2–3 題可點擊的引導範例問題。
- 冷啟動（trending 不足）時仍有引導；trending 足夠時優先用真實熱搜。
- 範例預產 + 快取，不在查詢時即時生成。

**Non-Goals**
- 不改檢索／答案／RAG。
- 不改 trending-queries 既有計分。
- 不即時生成。

## Decisions

### D1：資料表 `show_example_prompts`

新 model `backend/app/models/show_example_prompt.py`：
- `id` UUID PK
- `show_id` UUID FK → shows（ondelete CASCADE）
- `mode` enum（`index` / `semantic` / `chat`）
- `question` Text
- `ordinal` SmallInt（同 show+mode 內排序，0..2）
- `generated_at` timestamptz、`model` Text（記產生模型）
- Unique(`show_id`, `mode`, `ordinal`)
單支 alembic migration 建表。

### D2：生成服務 `example_prompts.py`

`generate_for_show(db, show_id)`：
- 取該 show 已轉錄集數的 `ai_summary`（抽樣彙整，避免 token 爆）、`guests`（去重）、topic terms（沿用 `episode_finders` 既有 topic 抽取）當素材。
- 對三個 mode 各組一段 prompt，要求 LLM 產 2–3 題**該模式風格**的範例：索引＝具體名詞/人名/地名關鍵字題；語意＝描述句（不需精確詞）；對話＝跨集統整題。
- 走 `ai_steps` 取 LLM endpoint/model（沿用 summary step 或新增 `example_prompts` step key；fail-open：生成失敗就不寫、不阻擋）。
- upsert 進 `show_example_prompts`（同 show+mode 先刪再寫，idempotent）。
- 成本：每 show 3 模式一次 LLM call（或合併一次），564 集規模屬小批次一次性。

### D3：觸發時機

- 鏈式：該 show 的摘要批次完成後 enqueue 一次 `generate_for_show`（參考 `episode-ai-summary` 鏈式）。
- Admin batch backfill：新增 admin endpoint 對全部 show 或單一 show 重跑生成（補既有節目）。

### D4：GET endpoint

`GET /shows/{show_id}/example-prompts` → `{ "index": [...], "semantic": [...], "chat": [...] }`（各 0–3 題字串，依 ordinal 排序）。公開（與 trending-queries 同等級，無敏感資料）。

### D5：前端

- **placeholder（per-mode 靜態 i18n）**：在 `src/i18n.jsx` 加三組 `mode_placeholder_index/semantic/chat`，`src/QueryPage.jsx` 三 tab 的 `Input` 各自套用。
- **chip fallback**：`src/TrendingQueriesChips.jsx` 既有打 trending；改為：trending 回 ≥3 題用 trending；< 3 題時打 `GET /shows/{id}/example-prompts` 取該模式預產範例顯示（chip 視覺標示為「範例」而非「熱搜」），點擊一樣帶入查詢執行。`TrendingQueriesChips` 需知道目前 mode（多傳一個 `mode` prop）。

### D6：模式對應的範例風格（生成 prompt 契約）

| mode | 範例風格 | 範例（節目示意） |
|------|---------|-----------------|
| index | 具體關鍵字/實體 | 「馬世芳」「歌單」 |
| semantic | 描述句 | 「他們怎麼看 AI 泡沫」 |
| chat | 跨集統整 | 「整理這個節目對獨立樂團的觀點」 |

## Implementation Contract

**Observable behavior**
- 對任一已生成範例的 show，`GET /shows/{id}/example-prompts` 回三模式各 0–3 題。
- 查詢頁三模式輸入框各顯示該模式的 placeholder。
- chip 槽位：trending ≥3 顯示熱搜；trending <3 顯示該模式預產範例（標示為範例）；皆無則不顯示 chip。點任何 chip 帶入查詢並執行。
- 生成為預產：使用者查詢過程不觸發任何 LLM 生成範例的呼叫。

**Interface**
- `GET /shows/{show_id}/example-prompts` → `{index: string[], semantic: string[], chat: string[]}`。
- Admin backfill endpoint（沿用既有 admin 認證）觸發 `generate_for_show`（單一或全部 show）。
- `generate_for_show(db, show_id) -> dict`（per-mode 題數）。

**Failure modes**
- 素材不足（show 無 ai_summary/guests）→ 生成跳過、不寫 row、endpoint 回空陣列、前端 chip 不顯示（不報錯）。
- LLM 生成失敗 → fail-open，不寫、不阻擋 ingest 鏈。
- endpoint 對未生成 show → 回三個空陣列。

**Acceptance criteria**
- migration upgrade/downgrade 可逆；`show_example_prompts` 表結構含上述欄位 + Unique 約束。
- unit/integration test：(a) `generate_for_show` 對有素材的 fixture show 寫入三模式各 ≥1 題；(b) GET endpoint 回正確 per-mode 結構；(c) 素材不足時跳過不報錯。
- 前端 prod smoke：冷啟動節目（trending <3）三模式各顯示範例 chip、點擊帶入查詢；熱門節目顯示 trending。
- `pytest backend/tests/test_example_prompts*.py` 全綠；`spectra validate` exit 0。

**Scope boundaries**
- **In scope**：`show_example_prompts` 表 + 生成服務 + GET/backfill endpoint + 鏈式觸發 + 前端 placeholder + chip fallback + i18n。
- **Out of scope**：檢索/答案邏輯、引用呈現（Change A）、trending 計分、即時生成。

## Risks / Trade-offs

- [LLM 產出品質參差] → fail-open + admin 可重跑 backfill；題數上限 3、長度上限，避免怪題。借鏡 `feedback_llm_auto_golden_set_needs_review`（LLM 自動產可能壞），但這裡是引導範例非 eval ground truth，容錯高。
- [素材彙整 token 成本] → ai_summary 抽樣 + 上限；一次性預產非每查詢。
- [trending 與範例混淆] → chip 視覺區分「熱搜」vs「範例」標籤。
- [新 show 尚未生成] → endpoint 回空、前端不顯示，不報錯；admin backfill 補。
