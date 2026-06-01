## Why

PodcastRAG 的逐字稿由 Whisper ASR 產生，固定會把專有名詞聽錯（已知 backlog：滅火器被聽成「咪有企」、世運被聽成「世韻」、寰宇龍虎豹被聽成「寰宇龍虎報」等）。這些錯字同時傷害兩件事：(1) 逐字稿閱讀體驗；(2) 更嚴重——因為搜尋索引（chunk 文字 + embedding + tsvector）直接複製自 segment 文字，使用者搜正確詞（例如「世運」）會完全找不到對應內容。目前只有臨時的 dataset alias 容錯，沒有來源端的修正機制。本 change 建立一套 deterministic、可控的錯字校正字典，並讓修正一路打通到搜尋索引，作為後續 EQ2b（LLM 同音異義字後處理）的安全網與評估基準。

## What Changes

- 新增 `asr_correction_terms` DB 表，存「錯字→正字」對照規則，每條含適用範圍（綁定節目 / 全站）、啟用旗標、備註與稽核欄位
- 校正採**整詞精確比對**（literal 完整字串比對，不啟用 regex／萬用字元），確保 deterministic 可控
- 每條規則**預設綁定單一節目（show-scoped）**，可手動升級為全站（global）
- 新增校正套用 service：依節目載入適用規則（global + 該節目的 enabled 規則），對逐字稿文字做整詞替換
- **新轉錄自動套用**：transcribe worker 在寫入 segment 與切塊之前先套校正，使逐字稿顯示與搜尋索引從一開始就是正字
- **既有逐字稿批次回填**：admin 觸發的背景任務，找出含錯字的 segment → 更新 segment 文字 → 只對受影響的 chunk 重組文字、重算 embedding 與 tsvector（非全量重算，成本受限於受影響的 chunk 數）
- 新增後台管理 tab：列表 / 新增 / 編輯 / 啟用停用 / 刪除規則 + 觸發批次回填，雙語、沿用 TOKEN 設計系統
- 新增 admin REST API：規則 CRUD + 批次回填觸發

## Capabilities

### New Capabilities

- `asr-correction-dictionary`: 錯字校正規則的資料模型、整詞精確比對與套用語意、適用範圍（綁定節目／全站）、新轉錄鏈式套用、既有逐字稿批次回填與受影響 chunk 的下游重算、規則 CRUD admin API
- `admin-asr-correction-ui`: 後台 ASR 校正管理 tab（規則 CRUD + 批次回填觸發 + 進度回饋），雙語 + TOKEN 設計系統

### Modified Capabilities

- `transcription-pipeline`: 轉錄完成後、切塊前，SHALL 對 segment 文字與全文套用該節目適用的 ASR 校正規則

## Impact

- Affected specs: 新增 `asr-correction-dictionary`、`admin-asr-correction-ui`；修改 `transcription-pipeline`
- Affected code:
  - New:
    - backend/app/models/asr_correction_term.py
    - backend/app/services/asr_correction.py
    - backend/app/api/admin/asr_corrections.py
    - backend/alembic/versions/ (新 migration 建 asr_correction_terms 表)
    - src/AdminAsrCorrectionTab.jsx
  - Modified:
    - backend/app/workers/tasks.py (新轉錄鏈式套校正 + 既有逐字稿批次回填 task)
    - backend/app/api/admin/__init__.py (註冊新 admin router)
    - src/AdminPage.jsx (pages 物件新增 admin-asr-correction tab)
    - src/Shared.jsx (後台 nav 新增入口項)
    - index.html (掛載 AdminAsrCorrectionTab.jsx script)
  - Removed: (無)
