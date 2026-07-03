## Context

量尺生產的兩次失敗經驗定義了本設計的邊界：(1) 2026-05-13 audit 證實 `build_golden_set.py` 全自動產題壞題率 ≥75%（根因：先產題再配錨 — 單關鍵字觸發深題、錨與題意不對齊、跨集錨含無關集）；(2) 手工一題一題共草品質高但 30 題耗掉一整個 session，5 個節目 ×30 題不可持續。既有可重用資產：staging 紀律（`_pending_review.json` + `--target-main` 三參數防呆）、chat-rag v2 schema（must/acceptable 分層 GT）、已校準判官（gemini-2.5-flash-lite，Spearman 0.8365）、answerability rubric（b20 GT audit 的 must=缺了會錯/acceptable=佐證）、13 個 agent tool 面（決定題型能測什麼）。

節目結構實測（2026-07-02 prod 量測）：來賓覆蓋率 — 屌 58%／台通 24%／塞掐 18%／曼報 15%／壹加壹 2%；歌單集只有屌（26 集）。題型配置必須 profile 驅動。

## Goals / Non-Goals

**Goals**
- 單節目 ≥30 題的生產成本從一整個 session 壓到「人審 30-60 分鐘內」
- 首輪壞題率（人審 reject 率）<40%（歷史基線 75%），回饋圈使第二輪更低
- 流程對任何節目可重複執行（profile 驅動，零 per-show hardcode）
- 產出直接符合 chat-rag v2 schema（must/acceptable/either 分層 GT）

**Non-Goals**
- 不做 prod query 回收軌（量太低；skill SOP 註記接入點）
- 不做固定環節結構化抽取（profile 留 `recurring_segments` 掛鉤即止）
- 不蓋 admin UI、不做自動排程
- 不在本 change 生產曼報/塞掐/台通的 golden set

## Decisions

### D1：Show Profiling = SQL 量測 + 靜態規則 quota 矩陣

新增 `backend/eval/scripts/show_profile.py`：對 show_id 跑固定量測（來賓覆蓋率、`%歌單%` 標題數、summary done 率、transcript 英文字元占比抽樣 20 集），輸出 `backend/eval/datasets/profiles/{show_slug}.json`。quota 規則為靜態可讀的 if 表（如 guests_coverage <0.10 → guest_find=0 並把配額回填給 fact/cross_episode），不做 LLM 決策 — profile 必須可解釋、可人工覆寫（JSON 手改後直接餵產題）。
- 替代案「LLM 看節目自由決定題型」否決：不可重現、不可審計。

### D2：anchor-first 產題（反轉舊流程）

改造 `build_golden_set.py`：每題生成順序 = 抽 episode（分層抽樣：長度×時間分布）→ 抽該集 chunk（或跨集抽 chunk 組）→ LLM 從 chunk 內容產題並自證 answerability → 錨定該 chunk id。與舊流程（LLM 憑 show 印象出題→事後找錨）的差異是錨先於題存在，錨不對齊類壞題在結構上不可能發生。
- cross_episode 題：抽 2-3 個同主題 chunk（用既有 topic 標籤或 embedding 近鄰）組成錨集，題目必須要求綜合。
- multi-turn 題成本高且結構特殊 → 不走自動產題，維持 handcraft（quota 內標記 `handcraft: true`，skill SOP 引導人工共草）。

### D3：預審分級 = 四檢查、retrieval 訊號只分級不否決

staging 檔每題附 `pre_review` 區塊，四項檢查：
1. **anchor 對齊**：LLM 二次驗證「只讀錨 chunk 能否回答此題」（用判官同款模型，非產題模型 — 避免自我背書）
2. **answerability rubric**：must/acceptable 分層是否成立（must 缺了會錯？）
3. **show_id 防呆**：錨 chunk 全數屬於目標 show（機械檢查，違反直接 reject — 這是唯一的自動否決，依據 2026-06-05 跨 show 碰撞教訓）
4. **retrieval 訊號**：題目丟實際 `/search`，記錄錨的 rank；**只作分級**（rank ≤20 → 輕審級傾向；>20 或 miss → 重審級）**不作否決** — 檢索不到的難題正是量尺價值（b20 教訓）
綜合打 `review_grade: light | heavy`。1/2 任一 fail → 強制 heavy。

### D4：人審 = 對話式全審、深淺有別、結構化 reject 理由

所有題目都過人審（Jacky 拍板：分級決定深淺、不決定跳過）。skill 引導對話式審核：輕審級批次呈現（每題一行摘要 + y/n）、重審級逐題呈現（題目 + 錨 chunk 原文 + rubric 判斷 + retrieval rank）。每個 reject/edit 記入 `backend/eval/datasets/_review_log.jsonl`，理由用固定枚舉：`anchor_mismatch | too_shallow | keyword_triggered | cross_ep_irrelevant | ambiguous | asr_typo_dependent | other(note)`。

### D5：回饋圈 = reject 模式 → negative few-shot 注入 + 壞題率追蹤

`build_golden_set.py` 產題前讀 `_review_log.jsonl`，把該節目（+全域）最常見 reject 理由對應的實例組成 negative few-shot 段落注入產題 prompt（上限 5 例防 prompt 膨脹）。每輪產題結束 skill 報告：本輪壞題率 vs 上輪、各 reject 理由分布。這是唯一的自我優化機制 — 便宜、可量測、無新基建。
- 替代案「fine-tune 產題模型」「自動調 quota」否決：樣本量級不足、過度工程。

### D6：載體 = skill 重寫 + 腳本改造，串接既有防呆

`.claude/skills/golden-set-builder/SKILL.md` 新寫（原規劃於 2026-05-07 但從未落地），承載端到端 SOP：profiling → 產題 → 預審 → 對話審 → `--target-main --reviewed-by --reviewed-at` 寫入主 dataset → 回饋圈報告。既有三參數防呆與 staging 紀律原樣保留。skill 內文含 prod query 回收軌的未來接入點註記（來源 = `events` 表 `search_executed`，需過濾 X-Eval 流量）。

## Implementation Contract

- `show_profile.py --show-id <uuid> [--backend-url]` → 寫 `profiles/{slug}.json`：`{show_id, slug, measured_at, metrics: {guests_coverage, playlist_titles, summary_done_ratio, en_char_ratio_sample}, recurring_segments: [], quotas: {fact, deep_dive, cross_episode, summary_overview, date_find, negative, multi_turn_handcraft, code_switch, guest_find, playlist_enum}}`；quota 規則以註解寫在腳本內、輸出可手改。
- `build_golden_set.py` 新介面：`--profile profiles/{slug}.json`（取代散裝 quota 參數）；輸出 staging item 附 `pre_review: {anchor_aligned: bool, answerability: {must_ok: bool, note}, show_id_ok: bool, retrieval_rank: int|null, review_grade: "light"|"heavy"}`；`--review-log` 預設讀寫 `_review_log.jsonl`。
- review log 行格式：`{ts, show_slug, item_id, verdict: "approve"|"approve_edited"|"reject", reason: <枚舉>, note, round}`。
- 首跑驗收（壹加壹）：profile 生成 → 產題 ≥40 候選 → 預審分級 → Jacky 對話審 → 主 dataset 寫入 ≥30 題（reviewed metadata 齊）→ 壞題率報告 <40% → 用 rag-eval-runner 跑一輪 baseline 證明 dataset 可被 eval 消費（分數不設 gate，只驗可跑通）。
- 回饋圈驗收：第一輪 review log 產生後，重跑產題 dry-run 證明 negative few-shot 有注入（prompt 內容含 reject 實例）。

## Risks / Trade-offs

- **預審模型自我背書**：產題與預審用不同模型（產題沿用 summary step 配置、預審用判官模型 gemini-2.5-flash-lite）降低相關性；人審全過是最終兜底。
- **輕審級漏壞題**：輕審仍是人眼掃過非跳過；首跑後比較輕審級的 reject 率，若 >15% 代表分級器需要收緊（規則調整列 follow-up）。
- **壹加壹 summary 已 done 247/261**，summary/overview 題型可產；塞掐/台通未來套用時 profile 的 summary_done_ratio 會自動把該題型 quota 壓 0，不會產出無法回答的題。
- **retrieval 訊號打分會慢**（每題一次 /search）：40 題約 2-3 分鐘，可接受；skill 註記可用 `--skip-retrieval-signal` 跳過（全部落重審級）。
