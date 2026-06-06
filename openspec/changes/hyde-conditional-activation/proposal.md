## Summary

把 HyDE 從「flag on → 無差別啟用」改成「兩階段召回門檻有條件啟用」：先用原問題向量（base_vec）召回一次，量測 query 與 top-k 召回 chunk 的詞面重疊度；只有在偵測到詞彙失配（重疊度低於校準門檻）時，才生成 HyDE 並補做第二輪召回。

## Motivation

`hyde-retrieval-landing`（2026-06-05 archive）的 prod A/B 證明無差別 HyDE 是雙面刃：對「問句講法 ≠ 答案講法」的真失配題有效（b20 @1719 prefilter-rank 78→17），但對 lexical 本來就對得上的題反而注入雜訊、把 rank 推後（b05 78.7→124.2 大退步，calibration 退步 3/8）。因此 `enable_hyde_retrieval` 落地後維持 off、未 flip。要讓 HyDE 能實際上線受益，必須只在真失配時才開——這正是本 change。

## Proposed Solution

1. **新增條件式啟用設定**：保留既有 master flag `enable_hyde_retrieval`（default off）不動；新增 `hyde_conditional_activation`（bool, default off）與門檻設定 `hyde_mismatch_overlap_threshold`（float）。只有 master flag on **且** conditional on 時，才走兩階段路徑；否則行為與現況位元等價。
2. **詞彙失配偵測訊號（主案 b）**：新增純函式量測 query 斷詞後的 token 與 base 召回 top-k chunk 文本（`RetrievedChunk.text`）的詞面重疊比例。重疊比例 < 門檻 → 判定詞彙失配 → 啟用 HyDE。此訊號直接對應 A/B 因果，且純後處理 base 召回結果、不動 `retrieve_hybrid` SQL。
3. **兩階段召回流程**：條件式啟用時，三個 retrieve 進入點先以 base_vec 跑一次 base 召回；偵測到失配才生成 HyDE、embed、以 HyDE 向量補做第二輪召回並改用其結果；未失配則直接沿用 base 召回結果，零額外 LLM / embed / 召回成本。
4. **門檻校準**：用既有 `backend/scripts/hyde_ab/run.py` harness 在 10 標靶（失配題）+ 8 calibration（lexical 對齊題）兩組上掃不同 overlap 門檻，選出能同時保住標靶 gain、不傷 calibration 的 cutoff，校準結果與選定門檻寫入 case study。
5. **觀測欄位**：`HydeResult` 擴充記錄「是否因失配而啟用」「量測到的 overlap 值」，供 `/admin/diagnose/prefilter-rank` 與 A/B harness 觀測條件式效果。
6. **fail-open 不變**：偵測或 HyDE 生成任何失敗一律 fail-open 回 base 召回結果，retrieve path 不得因此 5xx。

## Alternatives Considered

- **Query-only 召回前啟發式**（純看 query 長度/anchor 名詞判斷）：零額外召回成本，但失配與否取決於答案文本講法，光看 query 猜不準、誤判率高。否決。
- **改 SQL 暴露 lexical rank/score 當訊號（備案 a）**：需動 `retrieve_hybrid` 回傳結構與三段 RRF SQL，風險與改動面較大。保留為備案——若主案 b 詞面重疊度在 harness 校準時分不開兩組，再評估改採 lexical 分數門檻。

## Impact

- Affected specs: `hyde-retrieval`（修改既有 capability：新增條件式啟用、兩階段召回、失配偵測 requirement）
- Affected code:
  - Modified: backend/app/services/hyde_retrieval.py, backend/app/api/query.py, backend/app/core/config.py, backend/app/api/admin/diagnose_prefilter.py
  - New: backend/scripts/hyde_ab/calibrate_threshold.py（門檻校準腳本，複用既有 harness）, docs/case-studies/hyde-conditional-activation-calibration.md（校準結果，不進 git commit）
