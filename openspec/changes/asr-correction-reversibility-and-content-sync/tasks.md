## 1. 資料模型與 migration

- [x] 1.1 在 `backend/app/models/transcript_segment.py` 加 `original_text`（nullable Text），`backend/app/models/transcript.py` 加 `original_content`（nullable Text），並新增 alembic migration（兩欄預設 NULL、既有列不回填）。驗證：本機 Postgres `alembic upgrade head` 與 downgrade 皆通過；既有列兩欄為 NULL。

## 2. 校正套用：snapshot + content 同步

- [x] 2.1 修改 `backend/app/services/asr_correction.py` 的 `backfill_corrections` 非 dry-run 寫入路徑，達成 **Correction backfill recomputes affected chunks**（modified）：對文字改變的 segment，`original_text IS NULL` 時填校正前 text（不覆寫）；對受影響 transcript，`original_content IS NULL` 時填校正前 content，並把 `apply_corrections(content, rules)` 寫回 `transcripts.content`。`_fast_dry_run_preview` 維持唯讀不變。驗證：integration test（真實 Postgres）驗回填後 changed segment 有 original_text、transcript 有 original_content 且 content 為校正後；再跑一次回填 original_text 不被覆寫；dry-run 不寫這些欄位。
- [x] 2.2 修改 `backend/app/workers/tasks.py` 的 `_run`，達成 **Original transcript text preserved before correction** 與 **Transcript content reflects corrections**：寫 segment 時對文字改變者填 `original_text`（snapshot-once）；transcript 設 content 前若 `original_content IS NULL` 先存校正前 content（content 已是校正後，現況保留）。驗證：integration test 轉錄一集（mock LLM + 字典）後，changed segment 有 original_text、transcript original_content 為原始、content 為校正後。
- [x] 2.3 補「強制 content 重算」路徑（修補 EQ2d 前已回填、content 未同步的歷史集）：`backfill_corrections` 的 content 同步**不可只在「segment 文字有變」時觸發**——對 2026-06-02 EQ2c 前已回填的集，segment 已是正字、再回填 apply_corrections 為 no-op，content 永遠不會被帶到。需獨立判斷：對每個受影響 transcript，無論 segment 是否變動，都用該集適用規則對 `transcripts.content` 跑 `apply_corrections` 並寫回（idempotent：content 已正字則 no-op）。驗證：integration test 模擬「segment 已正字、content 仍錯字」的集，跑回填後 content 變正字、且 segment 不被重複 snapshot（original_text 不被覆寫）。

## 3. 還原能力

- [x] 3.1 在 `backend/app/services/asr_correction.py` 新增 `restore_episode(session, episode_id)`：把 segments `text` 還原回 `original_text`（僅非 NULL 者）、`content` 還原回 `original_content`、對還原的 segment 重算受影響 chunk（沿用 build_chunks diff + dual embedding + tsvector）、最後清空該集 segments 的 `original_text` 與 transcript 的 `original_content`；無任何 original 時回 affected=0。驗證：integration test 先校正再還原 → segment.text/transcript.content 等於原始、chunk 重算、original 欄位清空；無 original 的集回 affected=0。
- [x] 3.2 在 `backend/app/api/admin/asr_corrections.py` 新增 admin-only 還原端點（POST per episode，如 `/admin/asr-corrections/restore/{episode_id}`）呼叫 `restore_episode`，回受影響數。達成 **Episode transcript restore to original**。驗證：API test 驗 admin 還原回 200 + 受影響數、非 admin 403、無 original 的集回 200 affected=0。

## 4. 後台還原入口

- [x] 4.1 在 `src/TranscriptPage.jsx` 加 admin-only「還原原始逐字稿」入口：呼叫還原端點、操作前 confirm、成功後 reload 逐字稿；雙語、用 TOKEN 設計系統。驗證：browser smoke（admin）對一個已校正集按還原 → 逐字稿顯示回原始字、chunk/搜尋一致。

## 5. 測試與部署

- [x] 5.1 後端測試全綠（unit + integration，真實 Postgres 跑 backfill snapshot/content sync、_run snapshot、restore）。驗證：對應 pytest 全數通過；既有 EQ2a/b/c 測試不退步。
- [ ] 5.2 部署 migration + backend/worker/dispatcher/beat + 前端（同前模式）。prod smoke：對一個測試集做「校正→還原」全循環（可用 pilot 集），驗證還原後逐字稿頁全文、segment、搜尋皆回原始且一致。驗證：prod 還原端點回正確受影響數、逐字稿頁顯示原始字。
