## 1. 共用 Input 元件加 IME-safe onSubmit prop（落實 `Enter-to-submit MUST honor IME composition state`）

- [x] 1.1 修改 `src/Shared.jsx` `Input` 元件落實 `Enter-to-submit MUST honor IME composition state`：destructure 新增 `onSubmit` prop；新增 internal `handleKey(e)` — 先 `if (e.isComposing || e.keyCode === 229) return;`，再 `if (e.key === 'Enter' && onSubmit) { e.preventDefault(); onSubmit(e); }`，最後仍呼叫 `rest.onKeyDown?.(e)`。把 `{...rest}` spread 拆開：`onKeyDown` 從 rest 取出（不然兩條 handler 衝突），其餘照舊 spread
- [x] 1.2 確認 `Input` 仍允許 caller 傳 `onKeyDown`（spec scenario「Caller-supplied onKeyDown still fires」）— 在 handleKey 內呼叫 `restOnKeyDown?.(e)`
- [x] 1.3 在 `src/Shared.jsx` 檔尾 `Object.assign(window, {...})` 不需要動（Input 已 export）

## 2. QueryPage 兩個輸入框遷移到 onSubmit（落實 `QueryPage chat + semantic-search inputs MUST use the IME-safe submit path`）

- [x] 2.1 修改 `src/QueryPage.jsx` chat input 落實 `QueryPage chat + semantic-search inputs MUST use the IME-safe submit path`：把 chat 輸入框（目前在 chat panel 內、placeholder=「針對此節目內容提問...」那行）的 `onKeyDown={e => e.key === 'Enter' && handleSend()}` 換成 `onSubmit={handleSend}`
- [x] 2.2 修改 `src/QueryPage.jsx` 語意搜尋 input：把搜尋框（icon="search" 那行）的 `onKeyDown={e => e.key === 'Enter' && handleSearch()}` 換成 `onSubmit={handleSearch}`
- [x] 2.3 全檔再 grep 一次 `onKeyDown.*Enter` 確認沒有遺漏（預期：0 命中）

## 3. Prod 驗證

- [ ] 3.1 commit + push（commit message 含 spec scenario 對應、Phase C case study 不適用因 R3.x 範圍外）
- [ ] 3.2 等 Zeabur frontend build 綠（static deploy 快）
- [ ] 3.3 chrome-devtools-mcp 自動化驗證：登入 prod → 進「這又沒有很屌」chat 輸入框 → 用 `evaluate_script` 模擬 IME 流程：dispatchEvent compositionstart → 輸入字 → dispatchEvent Enter keydown with `isComposing: true` → 驗證 `handleSend` 沒呼叫（chat history 沒增加 user bubble）→ 結束 composition → dispatchEvent 一般 Enter → 驗證 handleSend 觸發
- [ ] 3.4 同樣對語意搜尋輸入框跑一次（驗 spec scenario「Semantic search input uses onSubmit prop」）
- [ ] 3.5 Regression check：輸入英文「abc」按 Enter → 送出（驗 spec scenario「Plain Enter DOES submit」）；空字串按 Enter → 按鈕仍 disabled、handleSend 不執行（驗 spec scenario「Empty-value Enter is no-op」）
- [ ] 3.6 把實際使用者手動複測 SOP 列給 user：用注音輸入「歌單那幾集講過什麼」逐字打 + 中途按 Enter 選字驗證不送出 → 完整句子按 Enter 才送出

## 4. 收尾

- [ ] 4.1 寫 release log entry（v1.7 內，date 2026-05-16，slug `chat-input-ime-composition-fix`，tag `fix`，user-perspective 講「用注音輸入時 Enter 選字不再誤觸送出」）
- [ ] 4.2 `/spectra-archive chat-input-ime-composition-fix` + 同步 memory `project_pending_followups.md` 把 issue #3 標完成
