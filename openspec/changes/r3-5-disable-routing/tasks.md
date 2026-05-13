## 1. Code 變更：翻 routing default（實作 Requirement: Two-layer episode routing SHALL be disabled by default；對應 design.md D1 — Default 翻向 vs 完全移除 routing code）

- [x] 1.1 [實作 spec requirement「Two-layer episode routing SHALL be disabled by default」] 改 `_should_skip_routing()` env default — 把 `backend/app/services/rag.py` 內 `_should_skip_routing()` 讀 env 的 `os.getenv("ENABLE_TWO_LAYER_ROUTING", "true")` 改為 `os.getenv("ENABLE_TWO_LAYER_ROUTING", "false")`。**完成條件**：env unset 時 `_should_skip_routing("任何兩個 jieba multi-char tokens 的 query")` 返回 `True`；env 設 `"true"` 時返回 `False`。**驗證**：跑 `pytest backend/tests/test_rag_routing.py -k should_skip_routing`（如測試不存在則在 1.2 補上）。
- [x] 1.2 補單元測試覆蓋兩種 env 狀態 — 在 `backend/tests/test_rag.py` 或新檔 `backend/tests/test_rag_routing.py` 加 test case：env unset → `_should_skip_routing` True；env `"true"` → False；env `"false"` 大小寫變體 → True。**完成條件**：`pytest` 對應 test 全綠。對應 spec scenario：「No env var set yields full-show retrieval」、「Env var set to "true" re-enables routing for diagnostics」、「Env var "false" is functionally equivalent to unset」。

## 2. Prod 環境變更（對應 design.md D1 ship 路徑 + Migration Plan step 2-3）

- [x] 2.1 設定 Zeabur backend service `ENABLE_TWO_LAYER_ROUTING=false` — 用 `npx zeabur variable update --id 69eb10360da29f05f49a4b0b -k ENABLE_TWO_LAYER_ROUTING=false -y -i=false`（**禁用** `variable create`，會 dump env）。**完成條件**：`variable list` 顯示該 key 存在且值為 `false`。**驗證**：抓一個 prod log 看 backend 起來後讀進的 settings 對應欄位。
- [x] 2.2 redeploy backend service — `npx zeabur service redeploy --id 69eb10360da29f05f49a4b0b -i=false`，等 deployment status 變 RUNNING。**完成條件**：`/stats` 200 + 新 deployment id 在 deployment list 第一筆且狀態 RUNNING。

## 3. Golden set audit 結果固化（實作 Requirement: Initial golden set covers 50 items across 5 types — 修訂版；對應 design.md D5 — golden set audit 變更綁入本 change 而非另起）

- [x] 3.1 [實作 spec requirement「Initial golden set covers 50 items across 5 types」修訂版] 移出 36 個 LLM-auto 壞題 — 從 `backend/eval/datasets/this-not-that-cool.json` 移除所有 `id` 以 `thisno-core-` 開頭的 items；保留 q01-q10 共 10 題。**完成條件**：`jq '.items | length'` 回 `10`；`jq '[.items[].id] | map(startswith("thisno-core-")) | any | not'` 回 `true`。對應 spec scenario：「Removed LLM-auto items SHALL not reappear」。
- [x] 3.2 補 q05 EP66 anchor — q05-uk-drill-features 的 `ground_truth_chunk_ids` 補上 `"ep:dbeecd79-f170-476a-b4e9-80e64eb49528@1423.22"`（EP66 講英國藝人 ego 的段落，2026-05-13 audit 確認屬於 UK Drill 語境）。**完成條件**：`jq '.items[] | select(.id=="q05-uk-drill-features") | .ground_truth_chunk_ids | length'` 回 `4`。
- [x] 3.3 寫入 audit 紀錄段落 — 在 dataset 頂層加 `audit` 欄位：`{"date": "2026-05-13", "removed_count": 36, "patched_ids": ["q05-uk-drill-features"], "reason": "LLM-auto-generated 壞題率 ≥75%，移出全部 thisno-core-*；q05 補 EP66 anchor"}`。**完成條件**：`jq '.audit.date'` 回 `"2026-05-13"`、`jq '.audit.removed_count'` 回 `36`。對應 spec scenario：「Counts are enforced at validation time」。

## 4. LLM-auto staging 政策落地（實作 Requirement: LLM-auto-generated items SHALL pass human review before inclusion；對應 design.md Non-Goals — 本 change 不擴 golden set，但需把政策寫死）

- [x] 4.1 [實作 spec requirement「LLM-auto-generated items SHALL pass human review before inclusion」] 在 `backend/eval/scripts/build_golden_set.py` 模組 docstring + 主流程加 staging guard — 在腳本頂部 docstring 加段落說明：「本工具輸出 SHALL 寫到 `backend/eval/datasets/_pending_review.json`，主流程 SHALL NOT 直接寫 `{show_slug}.json`」；並在 `if __name__ == "__main__":` 段加 default 輸出路徑為 `_pending_review.json`（要寫主 dataset 必須顯式 `--target-main` flag + `--reviewed-by <id>` + `--reviewed-at <iso8601>` 三者齊備）。**完成條件**：跑 `python -m eval.scripts.build_golden_set --help` 顯示 `--target-main` / `--reviewed-by` / `--reviewed-at` 三個 flag；沒給 review metadata 強寫主 dataset 應 `sys.exit(2)`。對應 spec scenarios：「Staged candidate without review SHALL NOT be merged」、「Reviewed candidate is merged into main dataset」、「Pure LLM batch insert is rejected at validation」。
- [x] 4.2 補 dataset 驗證腳本 / pytest — 在 `backend/tests/test_golden_set_validation.py`（新檔或既存檔案）加 test：拒絕 id 以 `thisno-core-` 開頭、且 `dataset.audit` 沒記 `reviewed_by` metadata 的 items 進主 dataset。**完成條件**：test 紅綠都覆蓋（壞 case 應 fail、好 case 應 pass）。

## 5. Case study 補 follow-up note（對應 design.md Context 段「2026-05-11 hotfix」歷史回顧）

- [x] 5.1 更新 `docs/case-studies/r32-routing-regression-2026-05-11.md` — 在文件結尾加新段落「## 2026-05-13 Follow-up」，說明：原本判斷 routing 是必要的 hotfix 基於 LLM-auto-inflated 測試集；audit 後純人類 query 上 routing Recall@5 = 0.0625、跳 routing = 0.4375（7x 反向）；本 case study 結論作廢，後續以 r3-5-disable-routing 的 design.md 為準。**完成條件**：檔案 grep 到 "2026-05-13 Follow-up" 段落且包含「結論作廢」字樣。

## 6. Ship 前驗證（對應 design.md D2 — Spike 三條診斷的具體資料、D3 — Latency 上限、D4 — Ship gate）

- [x] 6.1 跑 canary：q01 帶書名 query EP1 應進 top-5 — `curl -sk -X POST https://api.podcastrag.app/shows/45fc2462-17cf-42f5-98a7-68fe1a222228/search -H "Content-Type: application/json" -d '{"question":"節目名「這又沒有很屌」是怎麼來的？","k":5}'` 應回 top-5 包含 `episode_id` 開頭為 `9359c207`（EP1）。**完成條件**：response.results 至少 1 個 episode_id 開頭為 `9359c207`。此 canary 對應 design.md D2 spike B1 / B2 的修復驗證。
- [x] 6.2 跑 full eval：human-curated 10 題 Recall@5 ≥ 0.40（design.md D4 加分 gate）— 在容器內跑 `python -m eval.runners.run --dataset eval/datasets/this-not-that-cool.json --backend-url https://api.podcastrag.app --top-k 5 --out-dir /tmp/eval-out`，拉回 local `backend/eval/results/`。**完成條件**：summary md 的 `Recall@5 (episode)` ≥ 0.40。**FAIL 處理**：若 < 0.25 → 立刻 `zeabur variable update -k ENABLE_TWO_LAYER_ROUTING=true` 回滾、redeploy、本 change 不算完成、開診斷（對應 D4 FAIL 行）。
- [x] 6.3 觀察 P95 latency 30 分鐘（design.md D3 latency 上限）— 連續對 `/shows/{id}/search` 跑 20 query 量 P95，或拉 prod log 看 `latency_ms` 分布。**完成條件**：P95 ≤ 4500ms。**FAIL 處理**：若超過 → 不回滾、進 task 6.4 調 ef_search。
- [x] 6.4 (條件) 調 HNSW ef_search 補 latency — 只在 6.3 P95 > 4500ms 時做；在 `backend/app/services/rag.py` `_TRANSCRIPT_RRF_SQL` / `_DESC_RRF_SQL` 前加 `SET LOCAL hnsw.ef_search = 40`（從預設 80 降一半，trade 一點 recall 換 latency）。**完成條件**：重跑 6.2 + 6.3 後 P95 ≤ 4500ms 且 Recall ≥ 0.40。對應 design.md D3 Ship 條件退路。

## 7. Archive 配套（對應 design.md D6 — r3-4-embedding-model-swap 後續處理）

- [x] 7.1 r3-4-embedding-model-swap 補 design.md D7 follow-up — 在 r3-4 的 design.md 結尾加 D7 段落，說明 routing 才是 R3.2 ceiling 主因、embedding v2-large 維持 prod 但不再作為 r3-4 ship 唯一條件；本 change archive 時與 r3-4 同一輪 pair archive。**完成條件**：`openspec/changes/r3-4-embedding-model-swap/design.md` grep 到 "## D7" 且包含 "routing 才是主因" 字樣。
- [x] 7.2 r3-4 與本 change pair archive — 跑 `spectra archive r3-5-disable-routing` 後接著 `spectra archive r3-4-embedding-model-swap`（順序保持 r3-5 先，這樣 r3-4 archive 時 r3-5 已固化）。**完成條件**：`openspec/changes/archive/` 同日內出現 2026-05-13 開頭的兩個目錄。**注意**：archive 由 user 觸發，本任務只標 ready，不主動跑 archive。對應 design.md D6 pair archive 路徑。
