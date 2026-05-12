## 1. 加 2 個 env flag（quick code）— design D2 (env flag 短路 default)、design Behavior、design Interface / Data Shape、design Failure Modes、design Scope Boundaries (in-scope)；spec: 「Description hit cap is tunable via RAG_DESCRIPTION_CAP env」+「Show-name term filtering is tunable via RAG_SHOW_NAME_FILTER env」

- [x] 1.1 [spec: Description hit cap is tunable via RAG_DESCRIPTION_CAP env] `backend/app/services/rag.py` 加 module-level `_DESCRIPTION_CAP_RUNTIME` int，於 import 時讀 `RAG_DESCRIPTION_CAP`、parse 失敗 fall back 到 `DESCRIPTION_CAP` 並 stderr 警告一行（design Failure Modes）
- [x] 1.2 [spec: Description hit cap is tunable via RAG_DESCRIPTION_CAP env] `retrieve_hybrid` 中把原 `DESCRIPTION_CAP` 改用 `_DESCRIPTION_CAP_RUNTIME`
- [x] 1.3 [spec: Show-name term filtering is tunable via RAG_SHOW_NAME_FILTER env] 同檔加 `_SHOW_NAME_FILTER_ENABLED` bool，於 import 時讀 `RAG_SHOW_NAME_FILTER`（`false`/`0`/`off` → False，其餘 → True）
- [x] 1.4 [spec: Show-name term filtering is tunable via RAG_SHOW_NAME_FILTER env] `_build_ts_query` 把 `if tok in show_name_terms: continue` 改成 `if _SHOW_NAME_FILTER_ENABLED and tok in show_name_terms: continue`
- [x] 1.5 寫 `backend/tests/test_rag_retrieval_flags.py`：覆蓋 spec scenarios（env unset uses in-code default / env value 0 fully excludes description hits / malformed env falls back with warning / env unset preserves current strip behaviour / env set to false retains show-name tokens / embedding side never affected）
- [x] 1.6 跑 `pytest backend/tests/test_rag_retrieval_flags.py -v` 全綠
- [x] 1.7 commit + push（design Scope Boundaries 守住：default 行為等同現狀，純加 flag）

## 2. Phase 1 lever test（4 組 baseline）— design D1 (兩段式) + D5 (episode-level metric 主 gate)

- [x] 2.1 Zeabur backend service 加 env `RAG_DESCRIPTION_CAP=0`（用 stdout-suppress 法避免 dump env）→ redeploy → 等 stable
- [x] 2.2 跑組 (b)：`rag-eval-runner` skill v2.0 phase 0（preflight）+ canary 3 + full 48（episode-level，--persist-answers，--checkpoint-every 12）→ 結果歸檔 `backend/eval/results/`
- [x] 2.3 Zeabur backend env 改為 `RAG_DESCRIPTION_CAP=3`（恢復）+ `RAG_SHOW_NAME_FILTER=false` → redeploy → 等 stable
- [x] 2.4 跑組 (c)：同 phase 0 + canary 3 + full 48
- [x] 2.5 Zeabur backend env 改為 `RAG_DESCRIPTION_CAP=0` + `RAG_SHOW_NAME_FILTER=false` → redeploy → 等 stable
- [ ] 2.6 跑組 (d)：同 phase 0 + canary 3 + full 48
- [x] 2.7 Zeabur backend env 兩個都 delete（恢復 default）→ redeploy → 等 stable
- [ ] 2.8 把 4 組 eval（含 a baseline 2026-05-11 已跑的）的 episode-level Recall@5 / MRR / Judge mean / by-type 數據彙整成 delta 表格，append 進 `docs/case-studies/r32-routing-regression-2026-05-11.md` 的 「Phase 1 lever test evidence」 section
- [ ] 2.9 把該表格也 sync 進本 change `design.md` 的 「Phase 1 evidence」 section（implementation 補上）
- [ ] 2.10 判斷 Case A / B / C / D（依 design D3 的數值門檻）→ commit 進 case study 並選定 Phase 2 路徑

## 3. Phase 2 根因解（依 Case 分支）— design D3 (Case 分支判斷數值門檻)

- [ ] 3.1 Case A：把 `DESCRIPTION_CAP` 或 show-name filter 的 hardcoded default 改成 lever 過 gate 的值；env flag 機制保留；commit
- [ ] 3.2 Case B：兩個 hardcoded default 都改；commit
- [ ] 3.3 Case C：description chunker 細切實作（路徑：找出現在 chunk description 的程式碼位置；改成每段 ≤ 200 chars 切分，保留段落 boundary）+ 寫 unit test 驗 chunker 行為
- [ ] 3.4 Case C：re-embed backfill 全 414 集 description chunks — 用既有 `episode_description` backfill script 或寫 ad-hoc CLI；先 staging 一集驗證 idempotency
- [ ] 3.5 Case D：本 change 不 ship；把 4 組 lever 結果 + 推測結論寫進 case study；提議下一張 change（embedding swap / RRF refactor）
- [ ] 3.6 Case A-C：push code、redeploy backend 驗證

## 4. Final eval（v2.0 6 phase）— design D4 (Final eval 必走 v2.0 6 phase) + D5 (episode-level metric 主 gate)

- [ ] 4.1 Phase 0：preflight script 確認 env 全綠（per `rag-eval-runner` skill v2.0）
- [ ] 4.2 Phase 1：canary 3 + `--persist-answers` dump full I/O → 自己看一輪確認 input / output / scores 合理
- [ ] 4.3 Phase 2：派 sub-agent (Sonnet) 跑 metric sanity check — research question 是「R3.2 retrieval 命中率是否達到設計 target」，metric 是 episode-level Recall@5
- [ ] 4.4 Phase 3：variance baseline 同 prompt 同 dataset 跑 3 次，算 judge mean SD；確認 SD ≤ 0.05 才接受 single delta
- [ ] 4.5 Phase 4：full eval with `--checkpoint-every 10`
- [ ] 4.6 Phase 5：nohup + 落盤 log + 確認 PID 仍活著 ≥ 60 秒才宣告 launched
- [ ] 4.7 收齊 6 phase 證據；確認 episode-level Recall@5 ≥ 0.35 + SD ≤ 0.05
- [ ] 4.8 若 final eval 沒過 → 回到 Case 分支重判斷（可能 Case A 改成 Case B，或 Case B 改成 Case C）

## 5. Docs + 收尾

- [ ] 5.1 Append final 結果到 `docs/case-studies/r32-routing-regression-2026-05-11.md`（含 Phase 2 採用路徑、final eval 數字、結論）
- [ ] 5.2 起草 release log v1.7 entry（user 視角：「搜尋找到答案的比例改善了」+ 解釋為什麼）並寫進 `src/releaseLog.jsx`
- [ ] 5.3 更新 memory `project_pending_changes.md` 的「最近 archive」段（與本 change archive 後一起做）
- [ ] 5.4 commit + push 全部
- [ ] 5.5 跟 user 提議：archive 本 change + archive `r3-2-two-layer-topic-seg`（兩個 R3.2 milestone 一起 ship）
