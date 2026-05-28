## Why

b20 baseline 揭露 retrieve_hybrid 對 EP134（id `c1d87278-7dba-4fb1-930d-c2bd3a3461d2`）GT @1790.18 / @1808.78 整段沒撈到，導致 chunk_recall 下殺。`docs/case-studies/b23-retrieval-diagnostic-2026-05-27.md` Phase 1 follow-up 已把 root cause 縮到 2 選 1：A. chunking 邊界漏切 vs B. retrieve_hybrid 過濾規則排除。embedding cos sim 過低（C）已排除，因為 chunks 連 candidate pool 都沒進。本 change 跑純 diagnostic 鎖定 A 或 B，產出 RCA 報告，**不做任何 code 修復**，避免落入「先撈 baseline 再說」反 pattern。

## What Changes

- 跑三段 SQL diagnostic（Q1 → Q2 或 Q3，依結果分支）對 prod DB read-only 查詢，鎖定 root cause
- 產出 case study `docs/case-studies/chunk-level-retrieval-rca-b20-2026-05-27.md`：含 Q1/Q2/Q3 結果、root cause 判定（A 或 B）、修法方向、後續 change 建議
- 依結論 propose（不在本 change scope）下一個 change：A → `chunking-boundary-fix-ep134-style`；B → `retrieve-hybrid-filter-relax`
- 無 prod code 變動、無 deploy、無新 eval baseline

## Non-Goals

- 不動 chunking pipeline / retrieve_hybrid / embedding 任何 prod code
- 不跑新 eval baseline（沒 code 變動就沒意義）
- 不處理 b23 其他 follow-up（rerank input widening / agent pronoun grounding / judge pronoun-attribution）
- 不修 GT chunk_id @1790.18 / @1808.78 dataset 內容（audit_overlay 已 human-verified-2026-05-26）
- 不在本 change 內 propose / 實作後續修復 change
- 不寫 design.md（diagnostic-only、無新架構決策、無 cross-cutting 影響）

## Capabilities

### New Capabilities

- `chunk-retrieval-rca-b20-diagnostic`: 定義「對 EP134 @1790-1808 retrieve_hybrid miss 的 root cause 診斷協議」，含 Q1/Q2/Q3 SQL 查詢序列、root cause 判定規則（A vs B）、case study 交付物格式與證據要求。屬一次性 diagnostic 規格。

### Modified Capabilities

(none — 不動任何既有 prod code 或 spec 規範)

## Impact

- Affected specs: 新增 `openspec/specs/chunk-retrieval-rca-b20-diagnostic/spec.md`（apply 後 archive 落定）
- Affected code:
  - New: docs/case-studies/chunk-level-retrieval-rca-b20-2026-05-27.md
  - Modified: 無
  - Removed: 無
- Affected ops: prod DB read-only query（走 backend container exec，PGPASSWORD 走 env 不入 argv）
- Risk: 極低 — 無 deploy / 無寫入 / 無 code 變動
