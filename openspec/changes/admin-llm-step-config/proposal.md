## Why

目前 admin 後台的 LLM 設定有幾個問題：

1. **API 金鑰管理頁是純 mock**（`ApiKeysTab` 在 `src/AdminPage.jsx` 寫死四筆假資料，沒有後端 API）。
2. **LLM 模型設定頁只支援 Answer / Rewrite 兩個固定 LLM**（`llm_config` 是 singleton row，schema 寫死兩組 base_url + api_key + model）。
3. **金鑰跟用途綁死**：每個 LLM 用途要重複輸入 api_key，沒辦法多步驟共用同一把金鑰。
4. **轉錄與 embedding 沒有經過後台設定**：transcription provider 名稱讀 env、embedding 直接讀 `settings.openai_api_key`。換 provider 要 redeploy。
5. **接下來的 T3「每集 AI 摘要」需要新的第三個 LLM 用途**，現有 schema 沒地方放。

重構成「金鑰集中管理 + AI 處理步驟引用金鑰」之後，新增 AI 用途只需要在 admin 多加一個 step row，不必動 DB schema 也不必改 env。

## What Changes

- **BREAKING**：`llm_config` singleton 表 → 拆成 `api_keys` 表（每筆一把金鑰）+ `ai_steps` 表（每個 AI 用途一筆設定）。需要 migration 把現有 `llm_config.answer_*` / `llm_config.rewrite_*` 搬過去，再把 `settings.openai_api_key`（embedding + whisper 用）也匯入成一筆 `api_keys` row。
- 新增 5 個固定 AI 處理步驟（hardcoded `step_key`，不開放 admin 自行新增）：
  - `answer`（chat 類型，RAG 答案 LLM）
  - `rewrite`（chat 類型，查詢改寫 LLM）
  - `summary`（chat 類型，T3 每集摘要 LLM — 由本變更建立 row，由後續 `episode-ai-summary` 變更實際使用）
  - `embedding`（embedding 類型，RAG 向量化 — **必須使用 OpenAI 官方 provider**）
  - `transcription`（whisper 類型，可選 OpenAI Whisper API 或本地 faster-whisper）
- 新增後端 CRUD API：`/admin/api-keys`（list / create / update / delete）+ `/admin/ai-steps`（list / update；不支援 create / delete，因 step_key 固定）。
- 前端 `ApiKeysTab` 改接真後端，移除 mock；前端 `LLMTab` 重命名為 `AiStepsTab`，5 個 step 各一張表單，`base_url` 與 `model` 提供下拉選單（依選定的 api_key provider 列出常用值，仍允許自由輸入）。
- 前端的 step 表單**不再顯示 api_key 輸入欄位**，改成「選一筆已建立的 api_key」下拉。
- 後端服務層改寫：`services/rag.py`（answer / rewrite）、`services/embedding.py`、`services/transcription/factory.py` + 兩個 provider 改成從 `ai_steps` 讀設定（含對應 `api_keys` row），不再讀 `llm_config` 與 `settings.openai_api_key`。
- 雙語（zh / en）。

## Non-Goals

- **不支援自訂新 step**：step_key 由 codebase hardcode，admin 只能編輯既有 5 個 step 的設定。理由：YAGNI，避免做出 admin 可宣告新 endpoint 但前後端沒對應實作的怪狀態。
- **不做 api_key 加密儲存**：沿用現行 `llm_config.api_key` 用 plain text 儲存的策略（資料庫本身受 Zeabur 私有網路保護）。加密儲存留給未來變更。
- **不做 api_key 用量統計**：admin 看不到「這把金鑰被哪些 step 用過 / 用了多少次」。留給 R 系列或 U3 dashboard。
- **不做 provider 健康檢查**：已有 `admin-external-api-status-ui`，不重複。
- **不做版本歷史 / 回滾**：admin 改錯了就再改一次，不留 audit log。

## Capabilities

### New Capabilities

- `admin-llm-step-config`: 集中式金鑰管理（`api_keys` 表）+ 5 個固定 AI 處理步驟設定（`ai_steps` 表）。涵蓋資料模型、CRUD API、admin 兩個 tab 的 UI 行為，以及後端服務層從這兩張表讀取設定的契約。

### Modified Capabilities

(none. 既有 capability 的對外契約沒變，只有底層讀設定的來源換了，屬於實作細節)

## Impact

- Affected specs:
  - 新增 `openspec/specs/admin-llm-step-config/spec.md`
- Affected code:
  - New:
    - `backend/app/models/api_key.py`
    - `backend/app/models/ai_step.py`
    - `backend/app/api/admin/api_keys.py`
    - `backend/app/api/admin/ai_steps.py`
    - `backend/app/schemas/api_key.py`
    - `backend/app/schemas/ai_step.py`
    - `backend/app/services/ai_step_resolver.py`（提供 `get_step_config(step_key)` helper，讓服務層統一查 step + 對應 api_key）
    - `backend/alembic/versions/<rev>_add_api_keys_and_ai_steps.py`（新表 + 從 `llm_config` 與 env 搬資料）
    - `src/AiStepsTab.jsx`（取代 `LLMTab`）
  - Modified:
    - `backend/app/models/llm_config.py`（移除 singleton；migration 完成後檔案刪除，改由 `ai_step.py` 取代）
    - `backend/app/api/admin/__init__.py`（註冊新 router）
    - `backend/app/services/rag.py`（answer / rewrite 改讀 `ai_steps`）
    - `backend/app/services/embedding.py`（改讀 `ai_steps` 的 `embedding` step）
    - `backend/app/services/transcription/factory.py`（依 `ai_steps.transcription` 的 provider 與 model 決定 instance）
    - `backend/app/services/transcription/openai_provider.py`（從 step 讀 api_key + base_url，不讀 `settings.openai_api_key`）
    - `backend/app/services/transcription/faster_whisper_provider.py`（從 step 讀 model 名 / 路徑設定）
    - `backend/app/core/config.py`（移除 `openai_api_key` 必填欄位；保留為 startup 一次性 migration 來源後刪除）
    - `src/AdminPage.jsx`（`ApiKeysTab` 接真後端、`LLMTab` 改成 `AiStepsTab` 引用）
    - `src/Shared.jsx`（如有需要新增下拉元件）
  - Removed:
    - `backend/app/models/llm_config.py`（migration 後）
    - `backend/app/api/admin/llm_config.py`（如存在；改 `ai_steps.py`）

## Deployment Notes

對應設計 D5（Zero-downtime migration via dual-write），部署必須照下列順序，**不能合併也不能跳步驟**，否則會撞上「程式碼已找不到 `llm_config`、但 DB 還沒 drop 該表」或「DB 已 drop `llm_config`、但舊版程式碼還在跑會 500」的縫隙：

1. **Push 含本變更的 commit 到 GitHub**：Zeabur 觸發 build。完成後 backend / worker / dispatcher / beat 四個 service 用新映像啟動。
2. **Zeabur 自動跑 `alembic upgrade head` 至 Rev A `l0a1b2c3d4e5`**：建 `api_keys` + `ai_steps` 表 + 5 個 step row + 從舊 `llm_config` row 與 `OPENAI_API_KEY` env 匯入。**`llm_config` 表此 rev 仍保留**作為 fallback。
3. **Smoke test**：admin 進「LLM 模型」tab 應看到 5 個 step sub-form，answer / rewrite / embedding / transcription 四個都已自動帶入舊值；summary 是空的（待後續 `episode-ai-summary` 變更才會用到）。送一筆 RAG `/query` 確認 answer + embedding 走得通。
4. **手動跑 Rev B `m1b2c3d4e5f6`**：在確認新程式碼穩定運行後（建議至少 24 小時無 5xx）才 drop legacy `llm_config` 表：

   ```
   alembic upgrade m1b2c3d4e5f6
   ```

5. **驗證 Rev B**：在 backend service psql 跑 `\d llm_config` 應回 `Did not find any relation`；`SELECT step_key FROM ai_steps` 仍應回 5 筆。

**Rollback**：若步驟 3 smoke test 失敗，先 `alembic downgrade -1` 回到 `k9f0a1b2c3d4` 並 redeploy 上一版程式碼。Rev B 一旦跑了就不要 downgrade — downgrade 只重建空表 schema，原始 `llm_config` 資料不會回來，但 `ai_steps` 已是 source of truth，無需回填。

**前後依賴**：本變更必須在 `episode-ai-summary` 之前 deploy 完成（含 admin 在 ai_steps tab 把 `summary` step 的 base_url + model + api_key 設好），否則後者的 Celery summary task 會 raise `AiStepNotConfiguredError`。
