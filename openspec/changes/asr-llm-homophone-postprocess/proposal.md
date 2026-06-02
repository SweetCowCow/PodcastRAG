## Why

EQ2a 的 ASR 校正字典只能修「人工已建過」的已知錯字。Whisper 還會把大量沒人發現過的專有名詞聽成同音錯字（人名、樂團、節目術語），這些錯字讓使用者用正確名字搜尋時命中不到，也污染逐字稿與語意檢索。靠人工逐一發現再建字典無法規模化。本變更在轉錄完成後加一層 LLM 同音字偵測，自動找出未知同音誤聽，並讓這些發現以「待審核候選」沉澱進既有字典，由 admin 核准後成為跨集生效的正式規則。

## What Changes

- 轉錄 `_run` 在寫入 segment 前新增**第一層 LLM 同音字偵測**：整集逐字稿餵 LLM，回傳 `(錯字→正字)` pair 清單（僅詞級替換，不重寫句子結構或語氣，以保住關鍵字比對的專名精確）。
- LLM 回傳的 pair **本集即時套用**：用 EQ2a 既有的 `apply_corrections` literal 機制套到本集 segment，不受核准制阻擋（這集當下就修好）。
- 同一批 pair **沉澱為待審核候選**：寫入 `asr_correction_terms`，標記 `source='llm'`、`status='pending'`、`enabled=false`，預設 `scope='show'` 綁該節目。
- **第二層**：EQ2a 既有的已核准字典規則（`enabled=true`）照常 literal 套用。兩層合流後才 `build_chunks` → embedding。
- **核准制**：admin 在「ASR 校正」後台審核候選，核准 → `status='approved'`、`enabled=true`，自此跨集生效並進入第二層；駁回 → 刪除或標 `rejected`。未核准的候選不影響任何既有資料（靠 `enabled=false` 天然隔離）。
- LLM 偵測走既有 AI step 集中設定，新增 `asr_homophone` step（可在後台調 model / prompt）。
- **fail-open**：LLM 偵測失敗只記 warning，不阻擋轉錄；該集退回僅第二層字典校正。
- **成本防護**：偵測對長逐字稿是大輸入，提供 dry-run 估算「pilot 集數的 token 與預估成本」供確認後再跑。

## Non-Goals

- **全面回填既有逐字稿**：本變更先在「這又沒有很屌」挑 3–5 集做 pilot 驗證偵測品質與成本；對全節目／全站既有逐字稿套用 LLM 偵測，留待 pilot 結果確認後的後續變更。
- **句級重寫 / 語氣修正**：LLM 僅輸出詞級 pair，不重寫句子結構（避免 segment 時間戳對齊崩潰，且維持關鍵字比對精確）。
- **候選自動核准**：LLM 候選一律 `enabled=false` 待人工核准，本變更不提供自動核准模式。
- **跨節目自動套用**：LLM 候選預設 `scope='show'`，不自動升 global。

## Capabilities

### New Capabilities

- `asr-homophone-detection`: 轉錄後以 LLM 偵測未知同音誤聽詞，輸出詞級 pair，本集即時套用並沉澱為待審核候選；fail-open；走 AI step 集中設定；支援 dry-run 成本估算。

### Modified Capabilities

- `asr-correction-dictionary`: 資料模型加 `source`（manual/llm）與 `status`（pending/approved/rejected）欄位；規則解析只取已核准且 enabled 的規則；新增候選審核（核准 / 駁回）API。
- `admin-asr-correction-ui`: 後台新增「待審核候選」區，列出 LLM 偵測候選並提供核准 / 駁回。
- `transcription-pipeline`: 轉錄 `_run` 在第二層字典校正之前接入第一層 LLM 同音字偵測與本集即時套用。
- `admin-llm-step-config`: 新增 `asr_homophone` AI step，可調 model 與 prompt。

## Impact

- Affected specs: asr-homophone-detection, asr-correction-dictionary, admin-asr-correction-ui, transcription-pipeline, admin-llm-step-config
- Affected code:
  - New:
    - backend/app/services/asr_homophone.py
    - backend/alembic/versions/asr_homophone_candidate_fields.py
  - Modified:
    - backend/app/workers/tasks.py
    - backend/app/services/asr_correction.py
    - backend/app/models/asr_correction_term.py
    - backend/app/api/admin/asr_corrections.py
    - src/AdminAsrCorrectionTab.jsx
    - backend/app/services/ai_step_resolver.py
  - Removed: (none)
