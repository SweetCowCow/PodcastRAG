## Why

目前後台登入 Modal 下方顯示「示範帳號：admin / admin123」的提示文字。原本只有開發者自己測試使用，現在要邀請外部人員試用並蒐集意見，直接把帳密寫在登入框上會讓測試者無法給出真實的「未授權使用者」體驗，也容易讓非預期對象取得後台存取權。

## What Changes

- 移除 `src/App.jsx` 中 `AdminLoginModal` 元件下方的示範帳號提示段落（同時移除中英文兩個版本字串）
- 不變更登入驗證邏輯（仍維持 `admin` / `admin123` 的硬編碼驗證），僅移除 UI 上的明示
- 新增 `admin-login-modal-ui` capability，明文規範登入 Modal 不得顯示有效帳密提示

## Non-Goals

- 不在這次變更中替換硬編碼帳密為環境變數或後端驗證（屬於未來「正式帳號驗證系統」工作）
- 不調整 Modal 的視覺樣式、欄位、按鈕配置
- 不變更後台頁面的存取控制流程

## Capabilities

### New Capabilities

- `admin-login-modal-ui`: 規範後台登入 Modal 的 UI 行為，包括「不得在介面上顯示有效帳號或密碼提示」這條安全性需求

### Modified Capabilities

(none)

## Impact

- Affected specs: 新增 `admin-login-modal-ui`
- Affected code:
  - Modified: `src/App.jsx`（移除 `AdminLoginModal` 內第 79–81 行的示範帳號提示 `<p>`）
  - New: `openspec/specs/admin-login-modal-ui/spec.md`（由 archive 階段產生）
  - Removed: 無
