## Context

PodcastRAG 後台目前的 AI / LLM 設定散在四個地方：

1. `llm_config` singleton 表 — 存 answer + rewrite 的 base_url / api_key / model（schema 寫死兩組）。
2. `settings.openai_api_key` env — embedding (`services/embedding.py`) 與 OpenAI Whisper provider 共用。
3. `settings` 內其他 transcription 相關 env（`openai_whisper_chunk_size_mb`、`faster_whisper_model_dir` 等）— provider 切換靠 env，不靠 admin。
4. `src/AdminPage.jsx` 的 `ApiKeysTab` — **完全 mock**，沒有對應 backend table 或 API。

問題是：(a) 接下來 T3「每集 AI 摘要」要加第三個 chat LLM，現有 schema 沒位子；(b) admin 要切 transcription provider 還得 redeploy；(c) 同一把 OpenAI 金鑰在 embedding / whisper 兩處 hardcoded reference，未來換 key 要在程式碼搜很多地方。

本變更把所有 AI endpoint 設定收編到「`api_keys`（金鑰）+ `ai_steps`（用途）」兩張表，admin 改成單一控制台。後續所有新增 AI 用途（潤飾、相關推薦、…）只新增 `ai_steps` row 即可。

## Goals / Non-Goals

**Goals:**

- 金鑰只輸入一次，多個 AI 用途共用。
- Admin UI 一頁看完五個 AI 用途的設定狀態（answer / rewrite / summary / embedding / transcription）。
- 移除「換 transcription provider 要 redeploy」的痛點。
- Migration 必須**零停機**：上線後既有 RAG 查詢、轉錄佇列、embedding 不能因設定來源切換而中斷一次請求。
- 為 T3（episode-ai-summary）鋪好 `summary` step row 的位子，T3 開工時不需要再 alter table。

**Non-Goals:**

- 不支援 admin 自訂新 step（step_key 由 codebase hardcode 五個值，前端寫死順序與標籤）。理由：後台 UI 知道每個 step 是 chat / embedding / whisper 哪一型才能渲染對應表單；若允許自訂，要做動態 form schema，遠超 YAGNI 邊界。
- 不做 api_key 加密儲存（沿用既有 plaintext 策略，DB 受 Zeabur 私有網路保護）。
- 不做 api_key / step 用量統計，留給 U3 dashboard。
- 不做版本歷史 / 回滾。
- 不重做 `admin-external-api-status-ui`（健康檢查仍走那個 capability）。

## Decisions

### D1: Two-table split (api_keys + ai_steps)

**Decision**：`api_keys (id, provider, label, api_key, created_at)` + `ai_steps (step_key PK, step_type, base_url, model, api_key_id FK, extra_config JSONB, updated_at)`。

**Rationale**：

- 同一把金鑰可被多個 step 引用（OpenAI 金鑰同時供 embedding + 可能也供 transcription）。單表設計會讓金鑰重複 N 份，使用者改 key 時要記得 N 處同步。
- 金鑰的生命週期與 step 不同（金鑰可長期穩定，step 設定可能因實驗常變）。

**Alternatives considered**：

- _單一 `llm_endpoints` 表（金鑰跟 endpoint 同列）_：被否決，重複 + 同步噩夢。
- _api_keys 用 (provider) 當 PK 而不另開 id_：被否決，使用者可能想為同一個 provider 留多把（例如測試 key + 正式 key），加 `id` + `label` 較彈性。

### D2: Hardcoded step keys (5 fixed rows)

**Decision**：DB migration 預先 INSERT 5 個 row：`answer / rewrite / summary / embedding / transcription`。`/admin/ai-steps` 只開 LIST + UPDATE，不開 CREATE / DELETE。CHECK constraint 限制 `step_key IN (...)`。

**Rationale**：

- Hardcode 讓 backend 服務層可以直接寫 `resolver.get('answer')`，不用容錯「step 不存在」的情境。
- 預先 INSERT 讓 admin 第一次進頁面就看到 5 個空白 step 等填，不會 0 row 困惑。
- Migration 完成後 `summary` step 只有預設值（base_url 與 model 可能仍是空字串），admin 必須在 T3 上線前手動填好。本變更**不**負責生產可用的 summary 預設。

**Alternatives considered**：

- _空表，admin 自己 INSERT_：UX 差、且程式裡若 step 不存在要走預設值或丟錯，多出不必要分支。
- _config 表完全動態（admin 可新增任意 step）_：YAGNI，且前端要做動態表單。

### D3: step_type taxonomy (chat / embedding / whisper)

**Decision**：`ai_steps.step_type` 由 migration 寫入後不允許修改。對應規則：

| step_key | step_type | 設定欄位 | 後端 contract |
|----------|-----------|---------|---------------|
| answer | chat | base_url, model, api_key_id | `client.chat.completions.create(model=...)` |
| rewrite | chat | base_url, model, api_key_id | 同上 |
| summary | chat | base_url, model, api_key_id | 同上 |
| embedding | embedding | base_url, model, api_key_id | `client.embeddings.create(model=...)` |
| transcription | whisper | base_url（whisper-api 用）, model, api_key_id (whisper-api 用), extra_config (whisper-local 用 model_dir 等) | factory 依 `extra_config.provider`（`openai` / `faster-whisper`）決定 instance |

**Rationale**：三類 endpoint 的 API shape 不一樣（chat / embedding 都吃 base_url + model + api_key，whisper-local 不需要 api_key 但需要 `model_dir`）。前端用 `step_type` 切換表單欄位顯示。

**Alternatives considered**：

- _所有 step 同一個 schema，extra config 都丟 `extra_config` JSONB_：基礎設定讀寫變繁瑣（每次拿 base_url 都要解 JSON）。
- _每個 step type 一張表_：3 張表 schema 高度雷同，過度規範化。

### D4: Embedding provider restriction (frontend + backend)

**Decision**：

- 前端 `AiStepsTab` 在 embedding step 表單的 api_key 下拉**只列 `provider = 'openai'` 的 api_keys row**。
- 後端 `PUT /admin/ai-steps/embedding` validator 拒絕 `api_key_id` 對應的 `api_keys.provider != 'openai'` 之請求（回 422 + 訊息）。

**Rationale**：Zeabur AI Hub 不支援 `/v1/embeddings`（只代理 chat/completions），其他 provider（Anthropic / Google）也沒這個 endpoint。讓使用者選錯會在 RAG 查詢時直接 500，遠比 admin 儲存時擋掉要難 debug。

**Alternatives considered**：

- _只在前端擋_：使用者用 curl 直 PUT 仍能繞過。
- _不擋，讓後端服務層在 runtime 容錯_：失敗訊號回到使用者太晚。

### D5: Zero-downtime migration via dual-write

**Decision**：分三個 alembic revision 完成切換：

1. **Rev A（本變更內）**：建 `api_keys` + `ai_steps` 表 + 預先 INSERT 5 個 step row。從 `llm_config` 搬出 answer / rewrite 的設定到 `ai_steps`；從 `settings.openai_api_key` 建立一筆 `api_keys` row（provider=`openai`、label=`legacy-env-import`），把 embedding 與 transcription 的 `api_key_id` 指向它；transcription 的 `extra_config` 從現行 env 構造（如 provider 名 / chunk size）。**`llm_config` 表此 rev 保留**，不刪除。
2. **本變更程式碼層**：服務層全部改讀 `ai_steps`；舊的 `llm_config` 讀法砍掉。整支程式 deploy 完才會有對 `llm_config` 的 0 reference。
3. **Rev B（本變更內，但放在 Rev A 之後）**：drop `llm_config` table。在 Rev A 與本 deploy 完成後跑。

**Rationale**：

- Rev A 把 `ai_steps` 填好，舊程式仍在跑時，新表已有資料當 source-of-truth；新程式 deploy 後直接讀新表沒風險。
- Rev B 留到下一輪部署、或本變更內 deploy 完成後手動 `alembic upgrade` 觸發，避免「migration 跑了但程式碼還在讀舊表」的視窗。

**Risks**：開發者忘記跑 Rev B → `llm_config` 永遠沒清乾淨，但不影響功能（孤兒表）。Mitigation：tasks 寫明「deploy 後手動跑 Rev B + 驗證 `\d` 沒 llm_config」。

### D6: provider as free-form string

**Decision**：`api_keys.provider VARCHAR(50)`，admin UI 預設下拉提供 `openai / anthropic / google / zeabur-aihub` 四個常見值，但允許自由輸入。

**Rationale**：

- Provider 名沒有清晰 ground truth（OpenAI / Anthropic / Google / xAI / Mistral / 自架 / …）。
- 將來想加 provider 不該被 enum migration 拖。
- 後端只在 D4 那一處（embedding 限定 openai）依字串比對，多型別不必要。

## Risks / Trade-offs

- [⚠️ Migration 期間若 deploy 中斷] → 服務層程式碼還沒更新，但 `llm_config` 表仍在，整體仍能運作。Rev A 不刪舊表是關鍵安全網。
- [⚠️ Plaintext api_key 寫到新表] → 與現狀同等風險（DB 已存 plaintext），但「集中後攻擊面是否更大」值得記錄。Mitigation：等加密儲存變更時一併處理。
- [⚠️ Hardcode 5 個 step 違反 OCP] → 接受。新增 AI 用途頻率約 1-2 / 季，每次加 step 多 ~3 個 task（DB row INSERT migration、`step_key` enum 加值、前端加 UI 區塊），可控。
- [⚠️ Admin 改錯 embedding model 名 → RAG 全炸] → embedding model 改動不像 chat model 可任意換，要與既有 vector 維度對齊。Mitigation：前端 embedding step 表單加 warning「改 model 會讓既有 vector 失效，需要 reindex」。
- [⚠️ `extra_config` JSONB 結構漂移] → 建議在 backend schema 用 pydantic model 限制每個 step type 的 `extra_config` 欄位。Mitigation：新增 `schemas/ai_step.py` 為每個 step_type 定義 typed model。

## Migration Plan

1. 跑 Rev A（建表 + 寫入舊資料 + 5 個 step row）。
2. Deploy 新程式碼（服務層讀 `ai_steps`）。
3. Admin UI 進去確認 5 個 step 設定已從舊資料正確帶入（特別是 `summary` 是空白 step、`transcription` 的 extra_config 正確解析）。
4. 跑 Rev B drop `llm_config`。
5. （T3 上線前）admin 手動填 `summary` step 的 base_url / model / api_key。
