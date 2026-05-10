## Problem

R2.1 上 prod 後（commit d82afca，2026-05-10 20:23 台北 prod live），user 視覺驗證發現兩個 bug：

1. **「展開」button 點了沒反應** — SourceCard 顯示的 ai_summary 截斷到 60 字 + `…` + 「展開」link，但點下去 toggle 沒實際展開更多內容（後端只回 60 字版，沒回完整 summary）
2. **TranscriptPage URL `?t=99999` 直接 reload 跳回首頁** — URL 只有 `?t=` 沒有 `episode_id`，App reload 後從新 session 起，沒有 episode 上下文，路由判定走首頁。Deep-link 分享 / 開新分頁都會壞
3. （順手）**Highlight 顏色不夠搶眼** — `<mark>` 用 indigo 半透明 27% alpha，user 第一眼沒看出來。改加粗 + 下底線維持風格但提高可見度

## Root Cause

1. 後端 `enrich_hits()` 只回 `ai_summary_excerpt` （60 字截斷），沒回 full summary。前端「展開」邏輯 toggle state 存在但 expand 後沒有別的內容可顯示
2. Section 4 agent 的 deep-link 寫進 URL 時只放 `?t=`，沒同時放 `?episode_id=`。App.jsx reload 後 page state 預設回 select，沒有去解析 URL 的 episode_id
3. mark style 用 `TOKEN.accent + '44'` 太淡

## Proposed Solution

1. **後端 response 加 `ai_summary_full`** 欄位（不截斷的完整 summary 文字，nullable，episode 沒 ai_summary 時為 null）
2. **前端 SourceCard 「展開」toggle** 從顯示 60 字 ↔ 顯示 ai_summary_full 切換
3. **App.jsx URL 同時寫 `?episode_id=&t=`**；TranscriptPage init 時讀 URL `episode_id`，沒對應 episode 就 fetch；fetch 失敗才回首頁
4. **`<mark>` style** 加 `fontWeight: 600` + `borderBottom: 1px solid TOKEN.accent`

## Non-Goals

- 不做 server-side rendering / SSR（屬未來範疇）
- 不做 inline numbered citation 渲染（屬 R2.2）
- 不改 ai_summary 生成邏輯（後端摘要本身不變，只是多 expose 一個欄位）
- 不改 SourceCard 整體版型
- 不做 deep-link share 的 OG meta tag

## Success Criteria

1. 「展開」點下去顯示完整摘要文字（>60 字）
2. URL `?episode_id=<id>&t=99999` 直接 reload → 載入該 episode TranscriptPage + scroll 到頂（不跳首頁）
3. URL `?episode_id=<id>&t=300` reload → 載入 TranscriptPage + scroll 到 5:00 段落 + 高亮
4. Highlight 在 dark theme 下肉眼掃過 1 秒能識別
5. 既有 7 步驗證全綠

## Impact

- Affected code:
  - Modified:
    - `backend/app/schemas/query.py`（ChunkHit 加 `ai_summary_full: str | None` 欄位）
    - `backend/app/services/rag.py`（enrich_hits 一起 fetch ai_summary_full）
    - `src/Shared.jsx`（SourceCard 「展開」toggle 對應 ai_summary_full；mark style 加粗加底線）
    - `src/App.jsx`（navigation URL 同時寫 episode_id；URL parsing 邏輯）
    - `src/TranscriptPage.jsx`（init 時讀 URL episode_id 自動 fetch）
  - New:
    - `backend/tests/test_ai_summary_full_field.py`
