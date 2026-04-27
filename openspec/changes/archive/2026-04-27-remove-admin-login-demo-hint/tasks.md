## 1. Admin login modal SHALL NOT expose valid credentials in UI

- [x] 1.1 To satisfy "Admin login modal SHALL NOT expose valid credentials in UI": 編輯 `src/App.jsx`，刪除 `AdminLoginModal` 內第 79–81 行整段示範帳號提示 `<p>`（包含 `示範帳號：admin / ***REDACTED***` 與 `Demo: admin / ***REDACTED***` 兩種語系字串）
- [x] 1.2 To satisfy "Admin login modal SHALL NOT expose valid credentials in UI": 在瀏覽器以中文語系開啟 `index.html`，點擊右上角後台入口開啟登入 Modal，確認 Modal 內任何位置都看不到 `***REDACTED***`、`示範帳號`、`Demo:` 字樣
- [x] 1.3 To satisfy "Admin login modal SHALL NOT expose valid credentials in UI": 切換語系到英文，重新開啟 Modal，確認英文版同樣不再出現 `Demo: admin / ***REDACTED***`

## 2. Admin login modal SHALL keep its existing input and action affordances

- [x] 2.1 To satisfy "Admin login modal SHALL keep its existing input and action affordances": 確認移除示範提示後 `AdminLoginModal` 內仍保留說明文字、帳號 Input、密碼 Input、登入 Btn、取消 Btn 五個元素，且不殘留多餘空白節點或孤立的 `marginTop`
- [x] 2.2 To satisfy "Admin login modal SHALL keep its existing input and action affordances": 在瀏覽器分別以中文與英文語系檢視 Modal，確認帳號/密碼欄位 placeholder 與按鈕文字仍隨 `lang` 正確切換
- [x] 2.3 To satisfy "Admin login modal SHALL keep its existing input and action affordances": 輸入 `admin` / `***REDACTED***` 仍可成功登入後台（驗證僅移除 UI 文字、未動到驗證邏輯）
