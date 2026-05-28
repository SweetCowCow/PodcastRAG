## Problem

`retrieve_hybrid`（`backend/app/services/rag.py`）對 b20 EP134 黃金題目 GT chunks `9543a933` (@1790.18) / `f6cd079f` (@1808.78) 完全沒撈到，導致 `chunk_recall_grouped` 卡在 0.482、b20 該題 retrieval 端 100% miss。chunks 在 prod DB 存在且 boundary 完整對齊 GT timestamp（已由 archived `2026-05-27-chunk-level-retrieval-rca-b20-style` 證實）。

## Root Cause

來自 archived RCA case study `docs/case-studies/chunk-level-retrieval-rca-b20-2026-05-27.md`（含「2026-05-28 訂正」段，已更正原 AND-stacking 結論）+ 2026-05-28 prod DB probe 實證。

`_build_ts_query`（`backend/app/services/rag.py:211-253`）目前邏輯：

1. jieba 切詞
2. 過濾純標點 token（`re.fullmatch(r"\W+", tok)`）
3. 跳過 show-name filter terms（目前空集合）
4. 剩餘 token 用 `" | ".join(cleaned)` OR 拼接

關鍵問題：**沒有 stop-word 過濾、沒有 1-char drop**。對 b20 query「迪拉胖在 EP134 為什麼不挑一首振奮的開工歌？他選的歌想表達什麼概念？」，產出的 ts_query 是：

```
迪拉胖 | 在 | EP134 | 為 | 什麼 | 不 | 挑 | 一首 | 振奮 | 的 | 開工歌 | 他選 | 的 | 歌想表達 | 什麼 | 概念
```

含高頻 stop-word `的 / 不 / 在 / 為 / 什麼 / 一首`。Prod DB probe 結果：

- 該 ts_query 在百靈果 NEWS show 全 `transcript_chunks` 命中 **39,323 個 chunk**
- GT chunks 因弱信號 token 命中（只命中 `的 / 一` 之類常見字），全 show ts_rank 排序：
  - `f6cd079f` rank #18,348 / 39,323（ts_rank 0.0103）
  - `9543a933` rank #32,452 / 39,323（ts_rank 0.0059）
- `LIMIT :per_side=50` 砍完，GT chunks 連 lexical pool 邊都沒摸到
- Top 1-5 全是別集（EP72/EP69/EP26/EP64/15CM），完全沒 EP134 chunk

**真正的 root cause**：OR query 帶高頻 stop-word + 1-char token，pool 被 39K 噪音淹沒，signal chunks ts_rank 排太後被 LIMIT 砍掉。

注意：原 parked change `retrieve-hybrid-lexical-fallback-relax` 基於錯誤前提（誤以為 lexical 用 AND 拼接）已廢棄。

## Proposed Solution

修改 `_build_ts_query`，加兩條 noise-control filter：

**#1 Stop-word filter**（主修法）

維護 module-level stop-word set（中英文常見高頻字 + jieba 高頻虛詞）。在現有「過濾純標點」之後加一層「token in STOP_WORDS → skip」。預期把 b20 ts_query 從 16 token 砍到 ~6 個有信號 token：`迪拉胖 | EP134 | 挑 | 振奮 | 開工歌 | 他選 | 歌想表達 | 概念`。

**#2 1-char drop**（輔助）

`_build_ts_query` 既有 comment block（lines 240-253）已記錄「v4 ` | ` drop 1-char」是 bake-off 勝出方案，但實作沒落實。本 change 補實作：cleaned token 跳過 `len(tok) < 2`（CJK 單字幾乎都是 stop-word 級高頻字）。1-char 對 lexical signal 貢獻極低、對 noise 貢獻極高，drop 後雜訊大幅下降。

兩條 filter 並聯運作。即使 stop-word set 漏列某 1-char stop-word（譬如「裡」），1-char drop 仍會擋掉。

修改範圍鎖 `_build_ts_query` 一個函式。retrieve_hybrid / retrieve / retrieve_descriptions / retrieve_titles 都會自動受惠（共用同一個 query 生成函式）。

## Non-Goals

- 不動 jieba tokenizer 本身（不改 `tokenizer.tokenize` 或 custom dict）
- 不動 RRF weight / RRF_K / per_side / k 等 retrieval 超參
- 不動 chunking / embedding / prefilter / RRF merge 邏輯
- 不做 LLM query expansion（留待 Phase 3 備案）
- 不改 golden set / GT chunk_id
- 不新增 admin debug trace（待後續觀察期決定要不要加）

## Success Criteria

對比基準 `backend/eval/results/baseline-post-judge-v2-2026-05-27.json`：

- `chunk_recall_grouped` ≥ 0.55（baseline 0.482，目標 +0.07）
- `factual` ≥ 0.88（baseline 0.892，不退步）
- `hallucinated_cases` = 0（不增加）
- 無任何題 grading 從 PASS → FAIL（per-question regression check）
- 三模式（chat / semantic / keyword）皆通過上述條件
- b20 EP134 retrieval 端撈到至少 1 個 GT chunk（@1790 或 @1808）進 final top-K

驗證流程：

1. 本地 unit test 驗證 stop-word filter / 1-char drop 各自獨立可運作 + b20 query 預期輸出
2. Prod DB probe 重跑 b20 query 對應 ts_query，確認 lexical pool 命中總數從 39K 下降到 ~數百、GT chunks rank 進 top-50
3. prod redeploy 後跑三模式 baseline，落地 `backend/eval/results/baseline-stopword-filter-2026-05-28-{chat,semantic,keyword}.json`
4. 跑 diff vs `baseline-post-judge-v2-2026-05-27.json`，產出 per-question PASS→FAIL/FAIL→PASS 表
5. case study 落地 root cause 確認 + 達標判定

## Impact

- Affected specs:
  - Modified: `rag-query`（lexical query 生成新增 stop-word + 1-char filter 行為）
- Affected code:
  - Modified: backend/app/services/rag.py
  - New: backend/tests/services/test_build_ts_query_filter.py
  - New: docs/case-studies/retrieve-hybrid-lexical-stopword-filter-2026-05-28.md
  - New: backend/eval/results/baseline-stopword-filter-2026-05-28-chat.json
  - New: backend/eval/results/baseline-stopword-filter-2026-05-28-semantic.json
  - New: backend/eval/results/baseline-stopword-filter-2026-05-28-keyword.json
- Affected ops: prod redeploy（per env redeploy SOP）、三模式 eval baseline 跑完並落地
- Risk: 中
  - 主風險：stop-word list 過嚴可能誤砍某題型關鍵 token（譬如純疑問詞題「什麼是 RAG」砍掉「什麼」），但這類 query 本來就靠 semantic 側為主
  - per-question regression check 是主要 safety net
  - 1-char drop 對純英文 token（譬如「A」、「I」）幾乎無影響，CJK 1-char 砍掉風險可控
