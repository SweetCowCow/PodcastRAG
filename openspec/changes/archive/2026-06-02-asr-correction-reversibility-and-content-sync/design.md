## Context

ASR 校正（EQ2a 字典 + EQ2b LLM 候選）目前在兩處套用 literal 取代：轉錄 `_run`（本集即時套用 LLM pair + 第二層字典）與 `backfill_corrections`（既有逐字稿批次回填）。兩處都改 `transcript_segments.text` 與 `transcript_chunks`（text + dual embedding + tsvector）。缺口：(1) 原字被覆蓋無備份、不可還原；(2) `backfill_corrections` 沒同步 `transcripts.content`。本變更在這兩條寫入路徑加「原始快照 + content 同步」，並提供 per-episode 還原。

## Goals / Non-Goals

### In scope
- `transcript_segments.original_text`、`transcripts.original_content` 兩個 nullable 欄位 + migration。
- 校正套用時 snapshot-once 保存原文 + 同步 content（`_run` 與 `backfill_corrections` 兩路徑）。
- per-episode 還原 API + 後台逐字稿頁 admin 入口。

### Out of scope
- per-rule 逐條回退；RAGEC 偵測/候選審核改動；對 `original_text IS NULL` 的歷史已校正資料回溯補原文；chunk 重算演算法本身。

## Key Decisions

### D1：snapshot-once 語意（永遠保留「第一次校正前」原文）
- segment：套用校正時，若該 segment 文字「真的改變」**且** `original_text IS NULL`，才把校正前的 `text` 寫入 `original_text`；已有值則不覆寫。確保 `original_text` 永遠是最早的 ASR 原文，不會被第二次校正污染。
- transcript：某集第一次有任何 segment 被改時，若 `original_content IS NULL`，把校正前的 `content` 寫入 `original_content`。
- 理由：還原目標是「回到原始 ASR」，單一最早快照即足夠；多次校正疊加也只需一份原文。

### D2：content 同步
- `_run`：已寫校正後 content（現況），本變更只補「寫前先 snapshot `original_content`」。
- `backfill_corrections`（非 dry-run 寫入路徑）：對每個被改的 transcript，先 snapshot `original_content`（若 NULL），再把 `apply_corrections(content, rules)` 寫回 `transcripts.content`。dry-run 路徑（`_fast_dry_run_preview`）不變、仍唯讀。
- content 的校正用「該集適用的同一組 rules」套用，與 segment 一致。

### D3：還原語意（per episode，整集回原始）
- 還原 API（admin-only，POST per episode）：
  1. 撈該集 transcript 的 segments，對 `original_text IS NOT NULL` 者把 `text` 設回 `original_text`。
  2. 若 `original_content IS NOT NULL`，把 `content` 設回 `original_content`。
  3. 對「文字有變回」的 segment 重算受影響 chunk（重跑 `build_chunks` diff，與 backfill 同機制：text + dual embedding + tsvector）。
  4. 還原後清空該集 segments 的 `original_text` 與 transcript 的 `original_content`（回到「未校正、無備份」狀態；之後再校正會重新 snapshot）。
- 理由：清空快照讓「還原後再校正」能重新建立乾淨原文，避免殘留指向更舊狀態。

### D4：失效安全
- snapshot 與 content 同步都在既有交易內；失敗不可讓 segment 被改卻沒留原文。實作上「snapshot 原文」與「寫校正後文字」對同一 segment 必須同一 commit。
- 還原 API 對沒有任何 `original_text` 的集數回明確結果（affected=0），不報錯。

### D5：content 同步必須獨立於「segment 是否變動」（2026-06-02 prod 觀察補充）
2026-06-02 EQ2d 上線前已對「這又沒有很屌」跑過一次回填：segment + chunk 已正字、但 `transcripts.content` 仍留舊錯字（F2 缺口實際後果）。這些集 segment 已正字，之後再回填 `apply_corrections` 對 segment 是 no-op、不進「segment 文字有變」分支 → content 永遠補不到。
**決策**：content 同步**不掛在「segment 變動」條件下**。`backfill_corrections` 對每個受影響 transcript（該集有適用規則）一律對 `transcripts.content` 跑一次 `apply_corrections` 寫回（已正字則 idempotent no-op）。如此既修新回填、也修「segment 已正字但 content 沒跟上」的歷史集（task 2.3）。
**注意**：這些歷史集無 `original_text`（EQ2d 前校正的）→ 仍不可還原（Non-Goal 已涵蓋）；content 重算只負責「顯示一致」，不負責「可還原」。

## Risks / Trade-offs
- **儲存成本**：`original_text` 約等於再存一份逐字稿文字（僅被校正過的集數、且只存被改 segment 的原文）。可接受（文字量小）。
- **還原清空快照**：還原後原文不再保留，若使用者還原後後悔無法再還原回「校正版」——但校正規則仍在，重跑回填即可重建校正版。權衡合理。
- **歷史不一致**：本變更前已校正但 `original_text` NULL 的集數無法還原，content 也仍是舊字；明列 Non-Goal，靠重新轉錄處理。

## Migration Plan
1. migration 加 `transcript_segments.original_text`（nullable text）、`transcripts.original_content`（nullable text），預設 NULL；對既有列不回填（無原文可補）。
2. 部署 backend/worker/dispatcher/beat + 前端（同 EQ2a/b 模式，backend entrypoint 跑 migration）。
3. 上線後新校正的集數即具備還原能力；F6 全面回填在本變更之後才跑（先有安全網）。

## Open Questions
- 還原入口除了逐字稿頁 admin 按鈕，是否也要批次還原（per show）→ 暫不做，per-episode 足夠，需要再議。
