## 1. Backend: ai_summary_full 欄位

- [x] 1.1 在 `backend/app/schemas/query.py` 的 `ChunkHit` schema 加 `ai_summary_full: str | None = None` 欄位（落實 Success Criteria 1）
- [x] 1.2 在 `backend/app/services/rag.py` 的 `enrich_hits()` SQL 一起 fetch episode 完整 ai_summary（不截斷），寫進 hit 物件
- [x] 1.3 寫 `backend/tests/test_ai_summary_full_field.py`：mock episode with ai_summary 200 字 → 確認 response 同時有 `ai_summary_excerpt`(60字)跟 `ai_summary_full`(200字)；episode 無 ai_summary → 兩欄位都 null
- [x] 1.4 跑 backend pytest 確認沒退步

## 2. Frontend: 「展開」toggle 真的展開

- [x] 2.1 在 `src/Shared.jsx` SourceCard 元件，「展開」button 點擊 → state toggle expandSummary；展開時顯示 `src.ai_summary_full || src.ai_summary_excerpt`，「展開」label 變「收合」（zh）/「Show less」（en）
- [x] 2.2 ai_summary_full 為空時 button 不顯示（避免空 toggle）

## 3. Frontend: URL deep-link 帶 episode_id

- [x] 3.1 修 `src/App.jsx`：navigation 寫 URL 時同時 set `show_id` + `episode_id` + `t` 三個 param
- [x] 3.2 修 `src/App.jsx`：頁面 init 解析 URL — 若 `?show_id=<id>&episode_id=<id>` 存在 → fetch shows + episodes → set state → page route 設成 `transcript`
- [x] 3.3 改用 App.jsx 統一處理 fetch（不另動 TranscriptPage；fetched state 進去後 TranscriptPage 正常 render）
- [x] 3.4 邊界：fetch 404 / network 失敗 → window.alert toast + 清掉 URL params + 回首頁
- [x] 3.5 測試：手動跑 4 種 URL — **deploy 後 user 在 prod 測**

## 4. Frontend: highlight 加粗 + 底線

- [x] 4.1 在 `src/Shared.jsx` SourceCard 內 scoped `<style>` 加 `font-weight: 600 + border-bottom: 1px solid TOKEN.accent`（mark 實際定義位置在這，不在 QueryPage 683）
- [x] 4.2 TranscriptPage `<mark>` 已經用亮黃 (#fbbf24aa) 視覺夠強 — 不動（per spec「如果有」可選條款）

## 5. 部署 + 驗證

- [x] 5.1 commit + push → Zeabur 4 service rebuild redeploy
- [x] 5.2 user 跑 R2.1 完整 7 步驗證（全綠才通過）
- [x] 5.3 release log v1.6 entry 補對應 fix 項
