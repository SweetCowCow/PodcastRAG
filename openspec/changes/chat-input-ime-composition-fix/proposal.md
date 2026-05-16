## Problem

注音輸入法（與其他 CJK IME：倉頡、拼音等）打字時，使用者輸入聲韻符號 → 候選字浮窗出現 → 按 Enter **確認候選字**。`src/QueryPage.jsx` 兩個輸入框（chat 對話框 + 語意搜尋框）的 `onKeyDown` handler 抓到 Enter 就直接 `handleSend()` / `handleSearch()`，導致：

- 使用者打到一半（譬如想打「歌單那幾集」打到「歌單」就按 Enter 選字）→ query 被半途送出
- 已送出的 query 內容是被截斷的不完整字串
- 使用者要重新點輸入框、重新打整句、再小心不按 Enter 選字
- 體驗極差，對 CJK 用戶（即本專案幾乎全部用戶）日常使用構成阻擋

兩個現場：

- `src/QueryPage.jsx:465` — chat input
- `src/QueryPage.jsx:486` — search input

兩處皆無 IME composition guard。Codebase 全域 grep `isComposing` / `compositionend` 零命中。

## Root Cause

`onKeyDown={e => e.key === 'Enter' && handleSend()}` 沒區分「Enter 確認候選字」與「Enter 送出表單」兩種語意。DOM 標準提供 `e.isComposing` 與 legacy `e.keyCode === 229` 兩條判斷（IME composition 中時 `isComposing === true`，Safari/iOS 某些版本依賴 keyCode 229 偵測）。當前 handler 完全沒有這層 guard。

## Proposed Solution

把 IME composition guard 集中到 `<Input>` 共用元件，新增 `onSubmit` prop：

```jsx
// src/Shared.jsx Input 元件改動：
const Input = ({ value, onChange, onSubmit, placeholder, ...rest }) => {
  const handleKey = (e) => {
    if (e.isComposing || e.keyCode === 229) return;  // IME guard
    if (e.key === 'Enter' && onSubmit) { e.preventDefault(); onSubmit(e); }
    rest.onKeyDown?.(e);
  };
  // 把原本透過 {...rest} 傳的 onKeyDown 取出來自己處理
  ...
};
```

兩個 call sites 從 `onKeyDown={e => e.key === 'Enter' && handleSend()}` 改成 `onSubmit={handleSend}`。

**為什麼集中**：未來任何輸入框（譬如 admin 編輯框、modal 內輸入）使用 `<Input>` + `onSubmit` 就自帶 IME safety，避免同 bug 在新增輸入時再次出現。Two call sites 是「已知」case，但 codebase 還可能新增其他 Input 場景。

## Non-Goals

- **不改 `<textarea>` 場景**：本專案 textarea 都用「明確 Send button + 自由 Enter 換行」模式（譬如 ChatBubble 的回饋意見輸入），Enter 本來就不送出，沒有同 bug
- **不改 admin 編輯框類**：admin guests / tokenizer / API key 等編輯欄目前都靠「儲存」button 送出，無 Enter-to-submit，無同 bug
- **不導入大型 IME 處理函式庫**：兩行 `isComposing` guard 足夠，不需要 `@composition-handler` 之類 dependency

## Success Criteria

實作完成後 prod 驗證五項：

1. **IME 注音複測**：開 prod chat 輸入框，注音輸入法打「歌單那幾集」中按 Enter 選候選字 → query **不應送出**；打完整句後按 Enter → 送出
2. **英文/數字鍵盤行為不變**：純英數輸入「abc」按 Enter → 立刻送出（regression check）
3. **空字串保護仍生效**：輸入框空時按 Enter → 送出按鈕本來就 disabled，handleSend 不執行（regression check）
4. **語意搜尋框同行為**：搜尋框做同一複測 → IME 選字 Enter 不送出
5. **既有 unit test 套件全綠**：無 regression

## Impact

- Affected code:
  - Modified: `src/Shared.jsx`（`Input` 元件加 `onSubmit` prop + IME guard）
  - Modified: `src/QueryPage.jsx`（兩個輸入框從 `onKeyDown` 換 `onSubmit`）
  - New: 無
  - Removed: 無
- Affected specs:
  - New capability: `chat-input-ime-safety`（新 spec，覆蓋「Enter-to-submit 行為 MUST honor IME composition state」契約）
