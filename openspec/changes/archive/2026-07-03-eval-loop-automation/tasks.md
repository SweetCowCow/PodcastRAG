> Design 決策對應：任務 1.x 實作「D1：Show Profiling = SQL 量測 + 靜態規則 quota 矩陣」；任務 2.1 實作「D2：anchor-first 產題（反轉舊流程）」；任務 2.2 實作「D3：預審分級 = 四檢查、retrieval 訊號只分級不否決」；任務 3.1/3.2 與 4.3 實作「D4：人審 = 對話式全審、深淺有別、結構化 reject 理由」；任務 2.3 與 4.5 實作「D5：回饋圈 = reject 模式 → negative few-shot 注入 + 壞題率追蹤」；任務 3.1 實作「D6：載體 = skill 重寫 + 腳本改造，串接既有防呆」。

## 1. Show Profiling

- [x] 1.1 (D1 / Requirement: Show profiling drives question-type quotas) 新增 `backend/eval/scripts/show_profile.py`：對 `--show-id` 量測來賓覆蓋率、`%歌單%` 標題數、summary done 率、英文字元占比（抽樣 20 集 transcript）；靜態 quota 規則表（guests_coverage <0.10 → guest_find=0 回填 fact/cross_episode；summary_done_ratio <0.5 → summary_overview=0；playlist_titles=0 → playlist_enum=0）；輸出 `backend/eval/datasets/profiles/{slug}.json` 含 design Implementation Contract 的完整 schema（含 `recurring_segments: []` 掛鉤欄位）。驗收 = 對壹加壹跑出 `guest_find: 0`、對這又沒有很屌跑出 `guest_find > 0` 且 `playlist_enum > 0`
- [x] 1.2 profile 單元測試 `backend/tests/test_show_profile.py`：quota 規則表逐條（低來賓/低 summary/無歌單三情境）+ JSON schema 完整性 + 手改後可被 build_golden_set 讀取

## 2. anchor-first 產題改造

- [x] 2.1 (D2 / Requirement: Question generation is anchor-first) 改造 `backend/eval/scripts/build_golden_set.py` 產題核心為 anchor-first：分層抽 episode（長度×時間）→ 抽 chunk（cross_episode 抽同主題 2-3 chunk 組）→ LLM 從 chunk 內容產題 → 錨定該 chunk ids；`--profile` 參數取代散裝 quota；multi-turn 類標 `handcraft: true` 不自動產。staging 紀律與 `--target-main` 三參數防呆原樣保留
- [x] 2.2 (D3 / Requirement: Pre-review grading on staged items) 預審分級：staging item 附 `pre_review` 區塊 — anchor 對齊二次驗證（判官模型 gemini-2.5-flash-lite，非產題模型）、answerability rubric（must_ok + note）、show_id 機械防呆（違反 = 唯一自動 reject 並記 log）、retrieval 訊號（實打 `/search` 記錄錨 rank，`--skip-retrieval-signal` 可跳過全落 heavy）；綜合打 `review_grade: light|heavy`（檢查 1/2 任一 fail 強制 heavy）
- [x] 2.3 (D5 / Requirement: Reject patterns feed back into generation) 回饋圈：產題前讀 `backend/eval/datasets/_review_log.jsonl`，最常見 reject 理由 + 實例（上限 5）組 negative few-shot 注入產題 prompt；`--dry-run-prompt` flag 印出最終 prompt 供驗證注入；每輪結束印壞題率 vs 上輪報告
- [x] 2.4 產題單元測試 `backend/tests/test_build_golden_set_v2.py`：anchor-first 順序（錨先於題存在）、show_id 防呆 reject、review_grade 判定矩陣、negative few-shot 注入（mock review log）、staging-only 預設（無三參數不碰 main dataset）

## 3. Skill 與 review log

- [x] 3.1 (D4+D6 / Requirement: LLM-auto-generated items SHALL pass human review before inclusion) 新寫 `.claude/skills/golden-set-builder/SKILL.md`：端到端 SOP（profiling → 產題 → 預審 → 對話式人審【輕審批次一行摘要 y/n、重審逐題含錨原文+rubric+rank】→ 三參數寫入 main → 回饋圈報告）；review log 行格式與 reason 枚舉表；prod query 回收軌接入點註記（events 表 search_executed + X-Eval 流量過濾，未實作）；multi-turn handcraft 共草引導
- [x] 3.2 (D4 / Requirement: Human review verdicts are logged with structured reasons) review log 寫入實作：`_review_log.jsonl` append-only，行 schema `{ts, show_slug, item_id, verdict, reason, note, round}`；approve 寫入 main dataset 時 item 帶 reviewer id / reviewed_at / review round 溯源欄位

## 4. 壹加壹首跑（EQ5′ 第一批）

- [x] 4.1 跑 `show_profile.py` 產壹加壹 profile → Jacky 確認 quota 矩陣合理（guest_find 應為 0）
- [x] 4.2 首輪產題 ≥40 候選 + 預審分級完成；報告分級分布（light/heavy 比例）
- [x] 4.3 Jacky 對話式全審（輕審批次、重審逐題）；全程記 review log；**驗收 gate = 壞題率 <40%**（歷史基線 75%）；不足 30 題核准則跑第二輪（回饋圈生效後）補齊
- [x] 4.4 核准題以三參數寫入 `backend/eval/datasets/yi-jia-yi.json`（≥30 題、reviewed metadata 齊、必要的 handcraft sentinel/multi-turn 共草補入）
- [x] 4.5 回饋圈驗證：`--dry-run-prompt` 證明第二輪 prompt 含首輪 reject 實例；輸出兩輪壞題率對比報告
- [x] 4.6 用 rag-eval-runner skill 對新 dataset 跑一輪 baseline（分數不設 gate，驗證 dataset 可被 eval 框架完整消費：schema 相容、GT 分層欄位可計分）

## 5. 收尾

- [x] 5.1 spec sync 確認 + 時程 calibration 一行（feedback_time_estimation_calibration）+ 壹加壹首跑數據（壞題率/人審耗時/兩輪對比）記入 case study `docs/case-studies/eval-loop-automation-first-run.md`（不進 commit）
- [x] 5.2 roadmap 雙寫更新（EQ11 ✅、EQ5′ 標註壹加壹已完成第一批、曼報為下一批）
