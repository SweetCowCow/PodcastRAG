## 1. Backend: ai_summary_full 欄位

- [x] 1.1 在 `backend/app/schemas/query.py` 的 `ChunkHit` schema 加 `ai_summary_full: str | None = None` 欄位（落實 Success Criteria 1）
- [x] 1.2 在 `backend/app/services/rag.py` 的 `enrich_hits()` SQL 一起 fetch episode 完整 ai_summary（不截斷），寫進 hit 物件
- [x] 1.3 寫 `backend/tests/test_ai_summary_full_field.py`：mock episode with ai_summary 200 字 → 確認 response 同時有 `ai_summary_excerpt`(60字)跟 `ai_summary_full`(200字)；episode 無 ai_summary → 兩欄位都 null
- [x] 1.4 跑 backend pytest 確認沒退步

## 2. Frontend: 「展開」toggle 真的展開

- [ ] 2.1 在 `src/Shared.jsx` SourceCard 元件，「展開」button 點擊 → state toggle expandSummary；展開時顯示 `src.ai_summary_full || src.ai_summary_excerpt`，「展開」label 變「收合」（zh）/「Show less」（en）
- [ ] 2.2 ai_summary_full 為空時 button 不顯示（避免空 toggle）

## 3. Frontend: URL deep-link 帶 episode_id

- [ ] 3.1 修 `src/App.jsx`：navigation 寫 URL 時同時 set `episode_id` + `t` 兩個 param（取代現在只寫 `t`）
- [ ] 3.2 修 `src/App.jsx`：頁面 init 解析 URL — 若 `?episode_id=<id>` 存在 → page route 設成 `transcript` 並把 episode_id 放進 state
- [ ] 3.3 修 `src/TranscriptPage.jsx`：init 時若 episode 還沒 fetch → fetch episode + transcript；fetch 失敗才 fallback 首頁
- [ ] 3.4 邊界：URL `?episode_id=<不存在 id>` → fetch 404 → toast「找不到該集」+ 回首頁
- [ ] 3.5 測試：手動跑 4 種 URL（`?episode_id=<id>` / `?episode_id=<id>&t=300` / `?episode_id=<id>&t=99999` / `?episode_id=<bad-id>`），確認行為符合 Success Criteria

## 4. Frontend: highlight 加粗 + 底線

- [ ] 4.1 在 `src/QueryPage.jsx` line 683 (mark inline style) 加 `fontWeight: 600, borderBottom: '1px solid ' + TOKEN.accent, paddingBottom: 1`
- [ ] 4.2 在 `src/TranscriptPage.jsx` 對應 `<mark>` 樣式（如果有）同樣處理

## 5. 部署 + 驗證

- [ ] 5.1 commit + push → Zeabur 4 service rebuild redeploy
- [ ] 5.2 user 跑 R2.1 完整 7 步驗證（全綠才通過）
- [ ] 5.3 release log v1.6 entry 補對應 fix 項
