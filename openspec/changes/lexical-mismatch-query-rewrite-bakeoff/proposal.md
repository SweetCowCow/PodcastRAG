## Why

b20 與 b23 兩個 cross-episode golden case 的失敗都被 EQ3a 診斷歸到同一根因：**chunk-level 詞彙/語意失配**——使用者 query 的表面詞與 ground-truth chunk 幾乎零重疊（b20「中老年開工 vs 年輕差異」對 GT chunk @1719「安身之處」prefilter-rank 78、@1993 rank 7），現有 retrieval（ts_rank lexical + embedding hybrid + voyage rerank）召不回，且已證**非 voyage 弱、非 GT 髒**（GT 已 human-verified-2026-06-04）。

要修這類失配，候選手段有 query-expansion、HyDE、多向量（multi-vector）三條路，但它們互斥且成本/風險不同。2026-05-28 曾盲押 lexical-fallback 結果整條 change 退步全廢（教訓見 memory feedback_stopword_lexical_bridge_lesson）。因此**落地任何 query 改寫前，先用受控 bake-off 量測哪個手段真的把標靶 chunk 拉進召回**，而不是憑直覺押一個。

## What Changes

- 新增一個受控 bake-off harness，在固定測試案例上並排比較至少 4 個 arm：`control`（現狀 retrieval，不改 query）、`query-expansion`、`hyde`、`multi-vector`。
- 固定測試案例 = **b20 + b23**（皆 human-verified GT，b20 標靶 must=@1719+@1993；b23 標靶 must=@1766/@1819/@1847/@1866）+ 一組 calibration 防退步案例（沿用 calibration_8，確保改寫手段不傷害原本就能召回的 query）。
- 每個 arm 對每個案例量兩個 metric：**標靶 chunk 的 prefilter-rank**（標靶有沒有被拉進候選池、拉到多前）與 **chunk_recall@must**。因 arm 的 embed+retrieve 必須在 backend 端（需 db session 連 prod DB），新增一個 admin-only sibling endpoint `POST /admin/diagnose/lexical-bakeoff` 承載 arm 注入，arm 改寫邏輯放 backend service 層；harness 走 HTTP orchestrate、復用 `audit_voyage_pipeline.py` 的 prod session 樣板，不走線上 query API。
- 產出一份 bake-off 報告（落 `docs/case-studies/`），逐 arm × 逐案例列 prefilter-rank / chunk_recall / 成本（額外 LLM call 數、延遲）+ 勝者判定。
- **stop-the-line 決策契約**：bake-off 出結論後**不自動把勝者 merge 進 prod retrieval path**，停下來等 Jacky 拍板是否落地、由哪一條後續 change 落地。

## Capabilities

### New Capabilities

- `lexical-mismatch-query-rewrite-bakeoff`: 詞彙/語意失配 query 改寫手段的受控 bake-off 方法論與決策契約——固定 arm 集、固定測試案例與 metric、評分視角、防退步門檻、stop-the-line 落地閘門。

### Modified Capabilities

(none — 本 change 是離線 bake-off，不更動既有線上 retrieval 查詢的契約；落地勝者是後續獨立 change 的事)

## Impact

- Affected specs: 新增 `lexical-mismatch-query-rewrite-bakeoff`
- Affected code:
  - New: 新增 admin endpoint `POST /admin/diagnose/lexical-bakeoff`（`backend/app/api/admin/`）+ backend service 層 4 arm 改寫實作（`backend/app/services/`）+ harness orchestration script（`backend/scripts/lexical_bakeoff/`），bake-off 報告於 `docs/case-studies/`
  - Modified: 復用（唯讀）`backend/scripts/audit_voyage_pipeline.py` 的 prod session 樣板與 `rag.retrieve_hybrid`；既有 `backend/app/api/admin/diagnose_prefilter.py` 的 prefilter-rank 行為不更動；測試案例 GT 取自 `backend/eval/datasets/extended-multi-turn-40.json`（不改）
  - Removed: （無）
- 不碰 prod retrieval path、不碰 b22 routing、不碰 b23 narrative/topic-prefilter 解法軸、不改 GT
