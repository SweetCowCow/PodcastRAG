## Summary

讓 ASR 校正可還原（保存原始逐字稿）並把校正同步寫進 transcript 全文（content），作為大規模回填（F6/EQ2e）的安全網。

## Motivation

EQ2b 上線後檢視校正套用流程，發現兩個資料完整性缺口（F1、F2），在大量回填前必須補上：

- **F1 不可逆**：ASR 校正（轉錄時本集即時套用 + 批次回填）是 literal 字串取代，原字被覆蓋、DB 沒留原文。一旦核准了錯規則並套用，無法還原。目前唯一「巧合的原文」是 `transcript.content`（因 F2 沒同步才剛好留舊字），但那不可靠（無 segment 時間軸對應、新轉錄會覆蓋）。需要明確的原始備份 + 還原能力。

- **F2 content 未同步**：`backfill_corrections` 與轉錄 `_run` 對既有逐字稿回填時只改 `transcript_segments` + `transcript_chunks`，沒同步 `transcripts.content`（逐字稿頁顯示的整集全文）。導致 segment/搜尋是正字、但逐字稿頁全文仍是錯字，前後不一致。

兩者都改「校正套用的寫入路徑」，合併一條一起做最省，且互相依賴（還原要連 content 一起還原 → 需要 content 的原始快照）。

## Proposed Solution

- **原始快照（snapshot-once）**：
  - `transcript_segments` 加 `original_text`（nullable text）；`transcripts` 加 `original_content`（nullable text）。
  - 校正套用時（`_run` 與 `backfill_corrections`），對「文字真的改變」的 segment：若 `original_text IS NULL` 才填入校正前的文字（之後不再覆寫，永遠保留第一次校正前的 ASR 原文）；transcript 第一次有任何 segment 被改時，若 `original_content IS NULL` 填入校正前的 content。
- **content 同步**：校正套用時同步把校正後文字寫入 `transcripts.content`（`backfill_corrections` 補上此步；`_run` 已寫校正後 content，補上 `original_content` 快照）。
- **還原能力**：新增 admin-only 還原 API（per episode）：把該集 segments 的 `text` 還原回 `original_text`（僅 `original_text IS NOT NULL` 者）、`content` 還原回 `original_content`、重算受影響 chunk（text + embedding + tsvector）、還原後清空該集的 `original_text`/`original_content`（回到「未校正」狀態）。後台逐字稿頁提供 admin 「還原原始逐字稿」入口。

## Non-Goals

- 不做 per-rule 還原（只保留單一「第一次校正前」快照 → 還原是「整集回到原始 ASR」，非逐條規則回退）。
- 不動 RAGEC 偵測邏輯、候選審核、候選清單組成。
- 不對既有已校正、但 `original_text` 為 NULL 的歷史資料回溯補原文（沒有原文可補）；還原能力只對本變更上線後新校正的集數有效，舊集的不一致由「重新轉錄」處理。
- 不改 chunk 重算演算法本身（沿用 `build_chunks` + dual embedding + tsvector）。

## Alternatives Considered

- 只靠 `transcript.content` 當原文來源：不可靠（無時間軸、新轉錄覆蓋），且 F2 修好後 content 就變正字、原文消失。明確快照才正確。
- 每條規則存 diff 以支援逐條回退：複雜度高、與「整集還原」的實際需求不符；單一快照足夠。

## Impact

- Affected specs: transcription-pipeline（_run 寫 original 快照 + 同步 content）、asr-correction-dictionary（backfill 寫 original 快照 + 同步 content + 還原 API）
- Affected code:
  - New:
    - backend/alembic/versions（新 migration：加 `transcript_segments.original_text` 與 `transcripts.original_content`）
  - Modified:
    - backend/app/models/transcript_segment.py
    - backend/app/models/transcript.py
    - backend/app/services/asr_correction.py
    - backend/app/workers/tasks.py
    - backend/app/api/admin/asr_corrections.py
    - src/TranscriptPage.jsx
    - backend/tests/test_asr_backfill.py
    - backend/tests/test_asr_correction_transcribe_hook.py
  - Removed: (none)
