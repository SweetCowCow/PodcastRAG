## 1. 資料模型與 schema

- [x] 1.1 在 `backend/app/models/api_key.py` 建立 `ApiKey` SQLAlchemy model（對應 D1: Two-table split (api_keys + ai_steps) 的金鑰側 + D6: provider as free-form string）。欄位：id (UUID PK), provider (VARCHAR 50), label (VARCHAR 100), api_key (TEXT), created_at, updated_at；UNIQUE constraint `(provider, label)`；遵循「API key registry table」requirement。
- [x] 1.2 在 `backend/app/models/ai_step.py` 建立 `AiStep` SQLAlchemy model（對應 D1: Two-table split (api_keys + ai_steps) 的 step 側 + D2: Hardcoded step keys (5 fixed rows)），實作「AI step configuration table with hardcoded step keys」requirement。step_key (VARCHAR 50, PK), step_type (VARCHAR 20), base_url, model, api_key_id (FK → api_keys, nullable), extra_config (JSONB), updated_at；CHECK constraint 限制 step_key 五個值。
- [x] 1.3 在 `backend/app/schemas/api_key.py` 撰寫 pydantic schemas：`ApiKeyCreate`、`ApiKeyUpdate`、`ApiKeyResponse`（response 中 api_key 用 `last4 + ••••` 遮罩）。
- [x] 1.4 在 `backend/app/schemas/ai_step.py` 撰寫 pydantic schemas（對應 D3: step_type taxonomy (chat / embedding / whisper)）：`AiStepResponse` 含所有欄位；`AiStepUpdate` 為 union type，依 `step_type` 區分 `ChatStepUpdate` / `EmbeddingStepUpdate` / `WhisperStepUpdate`，每種 type 對 extra_config 欄位有 typed 限制。

## 2. Migration（Rev A 建表 + 匯入既有資料）

- [x] 2.1 撰寫 alembic Rev A：建立 `api_keys` 與 `ai_steps` 兩張表，含 UNIQUE / FK / CHECK constraint（對應 D5: Zero-downtime migration via dual-write 的第一階段）；同 migration 預先 INSERT 5 個 step row（answer / rewrite / summary / embedding / transcription），step_type 依 D3: step_type taxonomy (chat / embedding / whisper) 表填入。
- [x] 2.2 在同一 Rev A 中實作「Migration imports legacy llm_config and openai_api_key env」requirement：讀 `llm_config.id=1`，依 base_url hostname 推 provider（含 `aihub.zeabur` → `zeabur-aihub` / `api.openai.com` → `openai`），INSERT 對應 api_keys row，UPDATE answer / rewrite step。
- [x] 2.3 在同一 Rev A 中：讀 `settings.openai_api_key` env，若存在則 INSERT `provider="openai", label="legacy-env-import"` 一筆，UPDATE embedding step `api_key_id` + `base_url="https://api.openai.com/v1"` + `model="text-embedding-3-small"`。
- [x] 2.4 在同一 Rev A 中：讀現行 `settings` 的 transcription provider / model_dir / chunk_size，UPDATE transcription step 的 `extra_config`（JSON）+ 必要時 `api_key_id` / `base_url` / `model`。
- [x] 2.5 撰寫 alembic Rev B：drop `llm_config` table（需在 Rev A 之後、新程式碼 deploy 之後手動跑）。downgrade 重建 schema（不還原資料）。
- [x] 2.6 在 `backend/alembic/env.py` 確認新 model 被自動發現（import path 加進來）。

## 3. CRUD API（api_keys）

- [x] 3.1 在 `backend/app/api/admin/api_keys.py` 建立 router；GET `/admin/api-keys` 回 list（masked）。
- [x] 3.2 POST `/admin/api-keys`（對應「API key registry table」的 create scenario）：插入新 row，duplicate (provider, label) 回 409。
- [x] 3.3 PUT `/admin/api-keys/{id}`：更新 label 與 api_key（provider 不可改）。
- [x] 3.4 DELETE `/admin/api-keys/{id}`：若有 `ai_steps.api_key_id` 引用，回 409 + 列出引用的 step_key（對應「Soft delete blocked」scenario）。
- [x] 3.5 在 `backend/app/api/admin/__init__.py` 註冊 api_keys router。
- [x] 3.6 為 api_keys router 撰寫 pytest（auth fixture + 四個 CRUD endpoint + 409 衝突情境）。

## 4. CRUD API（ai_steps）

- [x] 4.1 在 `backend/app/api/admin/ai_steps.py` 建立 router；GET `/admin/ai-steps` 回固定五筆 row（對應「AI step configuration table」的 list scenario）。
- [x] 4.2 PUT `/admin/ai-steps/{step_key}`：依 step_type 套用對應 typed schema 驗證。step_key 不在五個 hardcoded 值內回 404。
- [x] 4.3 在 PUT 中實作「Embedding step provider restriction」requirement（對應 D4: Embedding provider restriction (frontend + backend) 的後端側）：embedding step 的 api_key_id 必須指向 `provider='openai'` 的 row，否則回 422。
- [x] 4.4 POST 與 DELETE 一律回 405 Method Not Allowed。
- [x] 4.5 在 `backend/app/api/admin/__init__.py` 註冊 ai_steps router。
- [x] 4.6 為 ai_steps router 撰寫 pytest（list 五筆、PUT chat / embedding / whisper 三種 step_type、embedding provider 限制 422、404 / 405 防呆）。

## 5. 服務層改寫（讀 ai_steps，棄用 llm_config 與 settings.openai_api_key）

- [x] 5.1 建立 `backend/app/services/ai_step_resolver.py`：暴露 `get_step_config(step_key)` 回 dataclass `StepConfig(base_url, api_key, model, extra_config)`；step_type 需要 api_key 但 row 上 `api_key_id IS NULL` 時 raise `AiStepNotConfiguredError`（對應「Backend service layer reads from ai_steps via resolver」requirement 的 fail-fast scenario）。
- [x] 5.2 改寫 `backend/app/services/rag.py`：answer 與 rewrite 兩處 OpenAI client 構造改用 resolver `get_step_config('answer')` / `get_step_config('rewrite')`。
- [x] 5.3 改寫 `backend/app/services/embedding.py`：移除 `settings.openai_api_key` 讀取，改用 `get_step_config('embedding')`。
- [x] 5.4 改寫 `backend/app/services/transcription/factory.py`：依 `get_step_config('transcription').extra_config['provider']` 決定回 OpenAI 還是 faster-whisper provider 實例（對應 D3 的 whisper step_type）。
- [x] 5.5 改寫 `backend/app/services/transcription/openai_provider.py`：建構時收下 `StepConfig`，使用其 base_url + api_key + model（不再讀 `settings.openai_api_key`）。
- [x] 5.6 改寫 `backend/app/services/transcription/faster_whisper_provider.py`：從 `extra_config` 讀 `model_dir` 與 model 名（不再讀 `settings.faster_whisper_model_dir`）。
- [x] 5.7 在 `backend/app/core/config.py` 把 `openai_api_key` 改為 Optional + 加註解「僅供 alembic Rev A migration 使用，runtime 不再讀」。
- [x] 5.8 為 `ai_step_resolver` 撰寫 pytest（chat 步驟 happy path、embedding 限定 OpenAI、whisper-local 不需 api_key、step 未設好時 raise）。

## 6. 前端：api_keys tab 接真後端

- [x] 6.1 在 `src/AdminPage.jsx` 把 `ApiKeysTab` 內部 mock state 移除，改為從 `apiFetch('/admin/api-keys')` 載入並 render。
- [x] 6.2 「新增金鑰」表單接 `POST /admin/api-keys`，label 與 provider 欄位為必填；provider 提供下拉預設 `openai / anthropic / google / zeabur-aihub` 但允許自由輸入（對應 D6: provider as free-form string）。
- [x] 6.3 加入「編輯」按鈕：開 modal 改 label / api_key，PUT `/admin/api-keys/{id}`。
- [x] 6.4 「刪除」按鈕：DELETE，遇 409 顯示 toast 列出哪些 step 仍引用。
- [x] 6.5 顯示 api_key 用 last 4 chars + `••••` 遮罩；提供「展開 / 隱藏」按鈕（仍只展開 last 4，因後端只回 last 4）。
- [x] 6.6 雙語（zh / en）所有按鈕、placeholder、錯誤訊息。

## 7. 前端：LLMTab → AiStepsTab

- [x] 7.1 新建 `src/AiStepsTab.jsx`，從 `src/AdminPage.jsx` import 並取代 `LLMTab` 在 routing map 的位子（key `admin-llm`）。
- [x] 7.2 GET `/admin/ai-steps` 取五筆，依固定順序 render 五個 sub-section（answer / rewrite / summary / embedding / transcription）。
- [x] 7.3 chat 類 step 的 sub-form：base_url 輸入框 + model 輸入框（依選定的 api_key 之 provider 列出常見值的 datalist）+ api_key dropdown（從 `/admin/api-keys` 拉）。對應「Admin UI presents api_keys and ai_steps as two separate tabs」requirement 中的 chat 表單。
- [x] 7.4 embedding 類 step 的 sub-form：同 chat，但 api_key dropdown 過濾 provider==openai（對應 D4: Embedding provider restriction (frontend + backend) 的前端側）。
- [x] 7.5 whisper 類 step 的 sub-form：先 render `extra_config.provider` dropdown（`openai` / `faster-whisper`）；選 `openai` 時顯示 base_url + model + api_key dropdown；選 `faster-whisper` 時顯示 `model_dir` 輸入 + model 輸入並 hide api_key。
- [x] 7.6 embedding step model 欄位變更時顯示 inline warning：「改 model 會讓既有 vector 失效，需要 reindex」/ EN 對應（對應 spec 的「Embedding model change warning」scenario）。
- [x] 7.7 PUT 後依 step_type 包裝對應 typed payload；422 錯誤訊息（含 embedding provider 限制）顯示在表單上方。
- [x] 7.8 移除 `LLMTab` 與所有 api_key 輸入欄位（在 ai_steps tab 中不再有 api_key 文字框）。
- [x] 7.9 雙語（zh / en）所有 sub-section 標題、欄位 label、placeholder、warning、錯誤訊息。

## 8. 整合測試與驗證

- [x] 8.1 整合測試：在乾淨資料庫上跑 Rev A，斷言 5 個 step row 已建立、`llm_config` 仍存在、`api_keys` 至少 1 筆（OpenAI legacy-env-import）。
- [x] 8.2 整合測試：模擬「`llm_config` 有 answer/rewrite 設定 + env 有 OPENAI_API_KEY」的初始狀態跑 Rev A，斷言 `ai_steps.answer` 與 `ai_steps.embedding` 已正確帶入（對應 spec 的 migration scenario）。
- [x] 8.3 整合測試：跑 Rev A 之後跑 Rev B，斷言 `llm_config` 表已被 drop。
- [x] 8.4 端到端煙霧測試：起 backend，admin UI 編輯 ai_steps.answer（換 model），送一筆 RAG `/query`，確認新 model 被使用。

## 9. 文件與部署

- [x] 9.1 更新 `docs/roadmap.md`：把 admin 重構列入「已 archive 變更」區塊（archive 完才填）。
- [x] 9.2 在 release log（`src/releaseLog.jsx`）草擬 entry（archive 後使用者再決定是否 commit）。
- [x] 9.3 部署順序文件：在 `openspec/changes/admin-llm-step-config/` 內 README 或 proposal 補一段 `Deployment Notes`，說明「先 deploy 程式碼 + Rev A，驗證 admin 可進入 → 再手動跑 Rev B」（對應 D5: Zero-downtime migration via dual-write 的雙寫過渡保護）。
