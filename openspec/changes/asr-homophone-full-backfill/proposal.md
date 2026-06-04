## Why

ASR 同音字校正系統（EQ2a–EQ2d）目前留下三個缺口，擋住「把校正套滿全站既有內容」這件事：

1. **既有集沒有正式的偵測入口。** LLM 偵測（`detect_homophones` + `persist_candidates`，RAGEC）目前只在兩個地方跑：轉錄 hook（新集自動）和 `scripts/homophone_pilot.py`（手動列 episode id 的 pilot）。偵測功能上線前就存在的舊集（全站約 565 集）從來沒被正式掃過一次，只跑過 pilot 5 集。

2. **套用作業跑起來像黑盒。** EQ2d 的套用回填（`backfill_asr_corrections`）是純背景 Celery，沒有 `bind=True`，只回 `task_id`：沒有進度、沒有狀態查詢、不能取消，`failed_chunk_ids` 也只在 task return dict 裡、前端讀不到。在這種狀態下跑「全站 565 集」的大 job 風險過高。

3. **approve 一條新規則後，舊集不會自動套用。** `approve_candidate` 只把規則設成 `enabled`，舊集裡的錯字要管理員自己記得再去手動觸發一次帶 `term_id` 的套用作業。這個兩步流程容易漏掉第二步，導致「規則生效了但歷史內容沒改」。

## What Changes

- **F6 — 偵測原有集數**：新增 admin 入口 + 獨立背景 task，per-show 一鍵對該節目全部既有集跑 LLM 偵測，產生 pending 候選。重用既有三件套（`estimate_detection_cost` 先做 dry-run 成本估 + 人工確認、`detect_homophones`、`persist_candidates`）。偵測**只產候選、不改任何逐字稿文字**（候選一律須經人工 approve 才會套用）。走自己的 task，不碰 `transcription_queue`。
- **F8 — 背景作業可觀測 / 可取消 + 批次 restore**：偵測與套用兩種長作業都改 `bind=True`，透過 Celery `update_state` 回報 `current/total` 進度 + 累計失敗；新增狀態查詢 endpoint（把 Celery PROGRESS meta + `failed_chunk_ids` 整理成 admin 可讀形狀，不是純轉發 `AsyncResult.state`）+ 取消 endpoint（`revoke(terminate=True)`）。取消語意 = 停止繼續跑、**不回滾**已完成部分；前端呈現進度 / 失敗 chunk。新增「批次 restore」：一鍵還原一次套用作業涉及的集（沿用 EQ2d 既有的 per-episode snapshot/restore 機制）。
- **F-approve — approve 候選時可選「順便套用原有集數」**：approve 一條候選時給一個選項，勾選後自動 enqueue 一個帶 `term_id` 的套用作業，把該規則套到既有集，補掉 approve 完舊集沒動的缺口。此作業共用 F8 的觀測 / 取消。

## Non-Goals

- **後台結構性重構**：ASR correction 後台 API 已經偏碎，但結構性重整留到 ASR EQ 系列（F4 詞典整合 / F7 一般同音字）收尾、需求穩定後另開 discuss，不綁進本 change（避免 scope creep + 過早抽象）。
- **偵測浮水印 / 增量機制**：明確不加「這集偵測過了」的標記。F6 是一次性歷史回填（新集走轉錄 hook 自動偵測），重跑全站成本僅約 $2–4，維護增量機制不划算。
- **F6 不套用、不改文字**：偵測階段只產 pending 候選，套用一律須經人工 approve；本 change 不引入任何「偵測完直接改逐字稿」的捷徑。
- **取消即回滾**：取消不做整批 rollback；救回已完成部分靠既有的 restore（套用層）與 reject/delete（候選層），與取消動作解耦。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `asr-homophone-detection`: 新增「對既有集批次偵測」的入口與背景作業（F6），偵測只產候選不改文字。
- `asr-correction-dictionary`: 套用作業改為可觀測 / 可取消、批次 restore、approve 觸發套用既有集（F8 後端 + F-approve 後端）。
- `admin-asr-correction-ui`: 後台新增偵測既有集觸發、背景作業進度 / 失敗 / 取消呈現、批次 restore、approve「順便套用」選項（F8 UI + F-approve UI）。

## Impact

- Affected specs: `asr-homophone-detection`、`asr-correction-dictionary`、`admin-asr-correction-ui`
- Affected code:
  - New:
    - backend/app/services/asr_detection_backfill.py（F6 偵測既有集的批次驅動器，iterate 一節目既有集 → 三件套 → 進度回報）
  - Modified:
    - backend/app/workers/tasks.py（套用 task 改 bind=True + update_state；新增偵測既有集 task）
    - backend/app/api/admin/asr_corrections.py（新增偵測既有集觸發、作業狀態查詢、取消、批次 restore endpoint；approve 加「順便套用」選項）
    - backend/app/schemas/asr_correction.py（新增偵測觸發 / 作業狀態 / 批次 restore 的 request / response schema）
    - backend/app/services/asr_correction.py（批次 restore 範圍解析；approve 觸發套用的串接）
    - src/AdminPage.jsx（偵測既有集按鈕、背景作業進度 / 失敗 chunk / 取消 UI、批次 restore、approve「順便套用」勾選）
    - openspec/LANGUAGE.md（新增 canonical term：偵測原有集數 / 套用原有集數）
  - Removed: (none)
