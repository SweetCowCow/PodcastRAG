## Why

Golden set 是所有品質改動的量尺，但目前的生產方式兩頭堵死：全自動 LLM 產題已證偽（2026-05-13 audit：`build_golden_set.py` 產出壞題率 ≥75% — 單關鍵字觸發、錨不對齊、跨集錨無關），全手工一題一題共草又太貴（30 題花掉一整個 session）。節目數已從 3 個成長到 5 個（塞掐 449 集＋台通 562 集剛入 prod），每節目 ≥30 題的手工路線不可持續。此外各節目結構差異大（壹加壹來賓覆蓋率僅 2%、這又沒有很屌有 26 集歌單特化集），題型配置不能一套 hardcode 到底。

## What Changes

- **Show Profiling（流水線第 0 步）**：新增自動量測腳本，對指定節目量測結構特性（來賓覆蓋率、標題 pattern、summary 就緒度、英文 token 占比抽樣），產出 show profile JSON，自動決定題型 quota 矩陣（如來賓覆蓋率 <10% 則 guest_find quota=0）。profile schema 預留 `recurring_segments` 欄位（台通推歌環節／塞掐片尾固定題等未來結構化抽取的掛鉤，本 change 不實作抽取）。
- **anchor-first 產題改造**：改造 `backend/eval/scripts/build_golden_set.py` — 產題順序反轉為「先抽 chunk → 從 chunk 內容產題 → 錨定該 chunk」（舊流程先產題再配錨是 75% 壞題率主因）；quota 由 show profile 驅動；輸出仍守 staging 紀律（只寫 `_pending_review.json`）。
- **Claude 預審分級**：staging 檔每題附預審結果 — anchor 對齊檢查、answerability rubric（must=缺了會錯／acceptable=佐證）、show_id 防呆、retrieval 訊號（錨是否出現在實際檢索 top-k；**只作分級訊號、不作否決** — 檢索不到的難題正是量尺價值）— 打成「輕審級／重審級」兩級。
- **人工全審（深淺有別）**：所有題目都過人審 — 輕審級快速掃過 y/n、重審級逐題看錨與判斷標準；每個 reject／修改記錄結構化理由（錨不對齊／題太淺／單關鍵字觸發／跨集錨無關／語意含糊等枚舉）到 review log。
- **reject 理由回饋圈（自我優化機制）**：review log 的 reject 模式在下一輪產題時作為 negative few-shot 餵回產題 prompt；每輪追蹤壞題率（review reject 率），驗證量化目標：首輪 <40%（歷史基線 75%）。
- **重寫 `golden-set-builder` skill**：`.claude/skills/golden-set-builder/SKILL.md` 目前不存在（2026-05-07 r1-eval-framework 規劃過但從未落地 main tree，`build_golden_set.py` docstring 指向幽靈檔案）。新寫 skill 承載完整 SOP：profiling → 產題 → 預審 → 對話式人審 → 寫入主 dataset → 回饋圈。
- **壹加壹首跑驗證**：用壹加壹電台（261 集、Jacky 最熟）跑完整一輪流水線產出 ≥30 題，即 EQ5′ 的第一批量尺；同時驗證流水線本身（壞題率、人審耗時）。

## Non-Goals

- **prod query 回收軌**：真實用戶 query 量目前太低，冷啟動是當下瓶頸；回收（含 admin/eval 流量過濾、去重）列為未來軌，本 change 只在 skill SOP 註記接入點，不實作。
- **固定環節結構化抽取**：台通推歌／塞掐片尾固定題的抽取與查詢面是獨立 Backlog 項；本 change 只在 show profile schema 預留掛鉤欄位。
- **admin UI**：人審介面就是對話（Claude 逐題呈現、Jacky 裁決），不蓋任何前端。
- **自動排程／dashboard**：不做週期性自動 re-run，跑一輪由人觸發。
- **曼報／塞掐／台通的 golden set 生產**：首跑只做壹加壹；其餘節目套用是 EQ5′ 後續批次，不在本 change 驗收內。

## Capabilities

### New Capabilities

- `golden-set-pipeline`: golden set 動態流水線 — show profiling、anchor-first 產題、預審分級、review log 與 reject 理由回饋圈、skill 工作流。

### Modified Capabilities

- `rag-eval-dataset`: 「LLM 產題必過人審」條款擴充為分級審制（staging 檔預審欄位、review log 格式、review 追溯 metadata）。

## Impact

- Affected specs: `golden-set-pipeline`（新增）、`rag-eval-dataset`（修改）
- Affected code:
  - New: backend/eval/scripts/show_profile.py、backend/eval/datasets/profiles/（show profile JSON 落點）、backend/eval/datasets/_review_log.jsonl（review log）、.claude/skills/golden-set-builder/SKILL.md
  - Modified: backend/eval/scripts/build_golden_set.py（anchor-first + profile 驅動 quota + 預審欄位 + negative few-shot 注入）
  - Removed: 無
