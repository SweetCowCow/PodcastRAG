## 1. Backend: 資料表與 migration

- [x] 1.1 新增 model `backend/app/models/show_example_prompt.py`（`ShowExamplePrompt`：id UUID PK、show_id UUID FK→shows ondelete CASCADE、mode enum index/semantic/chat、question Text、ordinal SmallInt、generated_at timestamptz、model Text；Unique(show_id, mode, ordinal)）＋一支 alembic migration 建 `show_example_prompts` 表（對應 design D1 與 Requirement「Per-show per-mode example prompt generation」的儲存契約）。驗證：`alembic upgrade head` 後 `\d show_example_prompts` 含所有欄位 + Unique 約束、`alembic downgrade -1` 可移除表。

## 2. Backend: 生成服務

- [x] 2.1 新增 `backend/app/services/example_prompts.py` 的 `gather_materials(db, show_id)`：取該 show 已轉錄集數的 ai_summary（抽樣彙整 + token 上限）、去重 guests、topic terms（沿用 episode_finders topic 抽取），回素材 dict（對應 design D2 取素材）。驗證：integration test 對 fixture show（含 2 集 ai_summary + guests）回非空素材；對無素材 show 回空 dict。

- [x] 2.2 在同檔加 `generate_for_show(db, show_id)`：對三 mode 各組 design D6 的風格 prompt 呼叫 LLM（走 ai_steps 取 endpoint/model；素材空或 LLM 失敗→fail-open 跳過不寫不拋），每 mode 取 2–3 題，先刪該 show+mode 舊 row 再寫入（idempotent）（對應 Requirement「Per-show per-mode example prompt generation」三個 Scenario）。驗證：integration test (a) 有素材 fixture → 三 mode 各 ≥1 row；(b) 無素材 → 0 row 且不拋；(c) 對已有範例的 show 重跑 → 不重複（同 show+mode row 數不增）。LLM 呼叫在 test 以 stub 取代。

## 3. Backend: Endpoint

- [x] 3.1 新增 `backend/app/api/example_prompts.py`：`GET /shows/{show_id}/example-prompts` 回 `{index:[], semantic:[], chat:[]}`（依 ordinal 排序、公開無認證、read 不觸發生成）；在 `backend/app/main.py` include_router（對應 Requirement「Example prompts retrieval endpoint」）。驗證：FastAPI test client (a) 已生成 show → 三 mode array 依序、(b) 未生成 show → 三個空 array 且無 LLM 呼叫（mock spy）、(c) route 註冊於 app.routes。

- [x] 3.2 在同 router（或 admin router）加 admin-authenticated backfill endpoint，觸發 `generate_for_show`（單一 show_id 或全部 show）（對應 Requirement「Generation triggered on ingest and via admin backfill」的 admin Scenario）。驗證：integration test 以 auth_admin 對單一 show 觸發 → 該 show 範例被（重）寫；非 admin → 403。

## 4. Backend: 鏈式觸發

- [x] 4.1 在既有 summary 批次完成的鏈式 enqueue 處（參考 episode-ai-summary 鏈式，`backend/app/workers/` 內）加 enqueue `generate_for_show`（show 摘要全完成後跑一次；idempotent 安全）（對應 Requirement「Generation triggered on ingest and via admin backfill」的 ingest 觸發）。驗證：unit test 對「該 show 摘要批次完成」事件 assert `generate_for_show` 被 enqueue（mock spy）一次。

## 5. Frontend: placeholder 與 chip fallback

- [x] 5.1 在 `src/i18n.jsx` 加三組 per-mode placeholder（`mode_placeholder_index` 引導關鍵字/實體、`mode_placeholder_semantic` 引導描述句、`mode_placeholder_chat` 引導跨集統整）＋ chip「範例」標籤文案；在 `src/QueryPage.jsx` 三 tab 的 `Input` 各套用對應 placeholder（對應 Requirement「Per-mode input placeholder」）。驗證：prod smoke 三 tab 輸入框各顯示不同且符合該模式語意的 placeholder。

- [x] 5.2 改 `src/TrendingQueriesChips.jsx`：多收一個 `mode` prop；先打 `GET /shows/{id}/trending-queries`，回 ≥3 顯示熱搜 chip；< 3 改打 `GET /shows/{id}/example-prompts` 取該 mode 範例顯示（chip 視覺標示為「範例」非「熱搜」）；皆空則不渲染；點 chip 帶入 query 並執行（沿用既有 onSelect）（對應 Requirement「Example chips fall back from trending to generated prompts」三個 Scenario）。`QueryPage` 三處使用 `TrendingQueriesChips` 傳入對應 mode。驗證：prod smoke (a) 冷啟動節目（trending<3）三模式顯示「範例」chip 可點執行；(b) 熱門節目顯示熱搜 chip；(c) 皆無時無 chip row。

## 6. 收尾

- [ ] 6.1 跑 `spectra validate per-show-mode-example-prompts` + 本 change 範圍 pytest（`backend/tests/test_example_prompts*.py`）全綠 + 對 prod 做 (i) admin backfill 一個冷啟動節目、(ii) 前端三模式 chip/placeholder smoke 截圖。驗證：(a) `spectra validate` exit 0；(b) pytest 全綠；(c) prod smoke 截圖貼 PR（冷啟動節目顯示預產範例 chip、點擊執行）。
