## ADDED Requirements

### Requirement: 來賓清單欄位

系統 SHALL 為每集 podcast episode 維護一個 `guests` 欄位，型別為 JSONB list of strings，預設值為空 list `[]`，不允許 NULL。

#### Scenario: 新建 episode 時初始化空 list

- **WHEN** RSS sync 建立新 episode 時 title 不含可辨識的來賓 pattern
- **THEN** `episodes.guests` MUST 寫入 `[]`

#### Scenario: 寫入後維持原順序去重

- **WHEN** 系統把 `["馬世芳", "裴社長", "馬世芳"]` 寫入 guests
- **THEN** 儲存值 MUST 為 `["馬世芳", "裴社長"]`（保留首次出現順序，去重）

### Requirement: RSS Title 來賓抽取

系統 SHALL 在 RSS sync 解析每集時，對 title 套用來賓 regex 抽取規則，將命中結果寫入 `episodes.guests`。

#### Scenario: 命中 Ft. 標記

- **WHEN** episode title 為 `"EP143｜這道菜真的有家常味嗎 Ft. 馬世芳 / 裴社長"`
- **THEN** 系統 MUST 抽出 `["馬世芳", "裴社長"]` 並寫入 `guests`

#### Scenario: 命中【ft.】方括號標記

- **WHEN** episode title 為 `"【ft.阿鳴】第一次來上節目"`
- **THEN** 系統 MUST 抽出 `["阿鳴"]` 並寫入 `guests`

#### Scenario: 大小寫不敏感

- **WHEN** episode title 含 `feat.` 或 `Feat.` 或 `FEAT.`
- **THEN** 系統 MUST 一律命中且抽出後續來賓字串

#### Scenario: title 無 pattern 命中

- **WHEN** episode title 為 `"EP100｜年終回顧"` 不含任何來賓 pattern
- **THEN** 系統 MUST 寫入空 list `[]`，不 raise error

### Requirement: 既有 episode 一次性 backfill

系統 SHALL 提供一次性 backfill script，對既有 episodes 重跑來賓抽取規則，補上 `guests` 欄位。

#### Scenario: backfill 對所有 episodes 跑一次

- **WHEN** admin 執行 `python -m scripts.backfill_guests --all`
- **THEN** 系統 MUST 對每個 episode 重新跑 regex 抽取，並 UPDATE `episodes.guests` 欄位

#### Scenario: backfill idempotent

- **WHEN** backfill 已跑過一次後再跑第二次
- **THEN** 結果 MUST 相同（regex 是純函數）；不 raise error；對既有手動編輯過的 guests **MUST 覆寫**（backfill 的語意是「以 RSS title 為真值重抽」）

##### Example: backfill 兩次的具體狀態

| episode title | 第 1 次跑後 guests | admin 手動改成 | 第 2 次跑後 guests |
|---|---|---|---|
| `EP143｜Ft. 馬世芳 / 裴社長` | `["馬世芳", "裴社長"]` | `["馬世芳", "裴老闆"]` | `["馬世芳", "裴社長"]`（覆寫掉 admin 改的） |
| `EP100｜年終回顧` | `[]` | `["主持人特集"]` | `[]`（覆寫成空 list） |
| `【ft.阿鳴】第一次來上節目` | `["阿鳴"]` | `["阿鳴"]` | `["阿鳴"]`（無變化） |

### Requirement: Admin 編輯 Guests

系統 SHALL 提供 admin endpoint 讓 admin 角色逐集修改 guests 欄位，支援修錯抽 / 補別名 / 完全清空。

#### Scenario: 取得單集 guests

- **WHEN** admin 對 `GET /admin/episodes/{episode_id}/guests` 發出請求
- **THEN** 回應 MUST 包含 `{episode_id, title, guests}`

#### Scenario: 更新單集 guests

- **WHEN** admin 對 `PUT /admin/episodes/{episode_id}/guests` 帶 `{"guests": ["馬世芳"]}` 發出請求
- **THEN** 系統 MUST 驗證每個 element 為非空 string、UPDATE `episodes.guests`、回應 200 + 更新後值

#### Scenario: 非 admin 拒絕

- **WHEN** 一般 member 對 `PUT /admin/episodes/{episode_id}/guests` 發出請求
- **THEN** 回應 MUST 為 403

#### Scenario: 列出單 show 全集 guests

- **WHEN** admin 對 `GET /admin/shows/{show_id}/guests` 發出請求
- **THEN** 回應 MUST 包含該 show 全部 episodes 的 `[{episode_id, title, published_at, guests}]`，按 `published_at desc` 排序
