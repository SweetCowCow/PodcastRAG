## Context

EQ2a（asr-correction-dictionary）已建立：`asr_correction_terms` 表（literal 字典規則）、`apply_corrections(text, rules)` literal 替換、`load_rules(session, show_id)` 取 enabled 的 global∪show 規則、轉錄 `_run` 在寫 segment 前逐段套校正、受影響 chunk 回填。本變更在其上加一層 LLM 偵測，並把偵測結果以核准制沉澱回同一張表。

## Goals / Non-Goals

### In scope
- 轉錄 `_run` 接入第一層 LLM 同音字偵測（整集 context、輸出詞級 pair）。
- LLM pair 本集即時套用（重用 `apply_corrections`）。
- LLM pair 沉澱為待審核候選（`source='llm'`, `status='pending'`, `enabled=false`）。
- `asr_correction_terms` 加 `source` / `status` 欄位；`load_rules` 改只取已核准且 enabled。
- 候選審核 API（核准 / 駁回）與後台 UI。
- `asr_homophone` AI step 設定。
- pilot：「這又沒有很屌」3–5 集；precision/recall 對 EQ2a 已知 6 條；dry-run 成本估。

### Out of scope
- 全節目 / 全站既有逐字稿的 LLM 偵測回填（pilot 後另開變更）。
- 句級重寫 / 語氣修正。
- 候選自動核准、跨節目自動升 global。

## Key Decisions

### D1：LLM 輸出詞級 pair，不輸出改寫全文
**問題**：transcript 是帶時間戳的 segment 陣列；若 LLM 吐改寫全文，切回 segment 會因字數/標點變動造成時間戳對齊崩潰。
**決策**：LLM 吃整集 context 做「判斷」，但只輸出 `[{wrong, correct}]` pair 清單。所有改寫一律走 `apply_corrections` 的 per-segment literal 替換，segment 邊界與時間戳零變動。
**結果**：第一層（LLM 偵測詞）與第二層（人工字典詞）共用同一 apply 機制，差別僅在「詞的來源」。

### D2：本集即時套用與跨集沉澱拆開
**決策**：LLM 回傳的 pair 在本集當下即用 `apply_corrections` 套到 segment（不查 DB、不卡核准），保證本集品質。同一批 pair 另寫入 `asr_correction_terms` 作為候選，供跨集生效用。
**結果**：核准制只決定「是否跨集 / 進第二層」，不影響本集校稿。

### D3：核准制以 `enabled=false` 天然實現
**決策**：候選寫入時 `status='pending'`、`enabled=false`。EQ2a 的 `load_rules` 本就只取 `enabled=true`，故未核准候選自動不被第二層與未來集帶到，零擴散。核准動作把 `status='approved'`、`enabled=true`；駁回設 `status='rejected'`（保留供未來偵測去重，不刪）。
**結果**：失效方向 fail-safe — 無人核准時系統靜止，不會擴散 LLM 誤報。

### D4：候選與既有規則去重
**問題**：LLM 可能偵測到已存在規則的 `wrong`（已核准或已駁回）。`(wrong, scope, show_id)` 有唯一約束。
**決策**：寫候選前先查同 `(wrong, scope, show_id)`：已存在（任何 status）則跳過，不重複插入、不覆寫既有 status。本集即時套用不受影響（即時套用不依賴 DB）。
**結果**：避免唯一約束衝突，且已駁回的詞不會被 LLM 反覆重建為待審。

### D5：LLM 偵測走既有 AI step 集中設定
**決策**：新增 `asr_homophone` step，沿用 `get_step_config` 取 model/prompt。prompt 約束 LLM：只回同音誤聽的詞級 pair、保留原專名拼寫意圖、不確定則不回、輸出嚴格 JSON 陣列。
**結果**：model/prompt 可在後台調，與 embedding/summary/topic 等 step 一致。注意 AI Hub 不保證 `response_format=json_object`，解析時須 strip code block 後 `json.loads`。

### D6：fail-open
**決策**：LLM 呼叫或解析失敗 → log warning、第一層回空 pair，轉錄續走第二層字典校正完成。
**結果**：偵測層永不阻擋轉錄。

## Risks / Trade-offs
- **LLM 誤報**：可能把正確專名判為錯字。緩解：核准制（人工把關）+ 本集即時套用雖會改本集，但 pilot 階段集數少、可人工檢視；pilot 通過才考慮放寬。
- **成本**：整集為大輸入，每集一次 LLM call。緩解：dry-run 先估 pilot token/成本；pilot 限 3–5 集。
- **本集即時套用的 LLM 誤改**：本集即時套用不經核准，理論上 pilot 集可能被 LLM 誤改。權衡：pilot 範圍小、可逐集人工驗；evaluation 對 EQ2a 已知 6 條算 precision/recall 量化誤報率，作為是否擴大的依據。

## Migration Plan
1. migration 加 `source`（text, default `'manual'`）、`status`（text, default `'approved'`）欄位；既有列回填為 `manual`/`approved`（維持 EQ2a 行為不變）。
2. `load_rules` 加 `status='approved' AND enabled=true` 條件。
3. 後端 / worker / dispatcher / beat + 前端部署（同 EQ2a 模式，僅 backend entrypoint 跑 migration）。
4. 後台設定 `asr_homophone` step（model/prompt）。
5. pilot：對「這又沒有很屌」3–5 集跑偵測 → 檢視候選 → 核准/駁回 → 量測 precision/recall 與成本。

## Open Questions
- pilot 通過後的全面回填策略（哪些節目、批次大小、成本上限）→ 後續變更處理。
