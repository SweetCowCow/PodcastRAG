## 1. Admin sweep endpoint + baseline 量測

> **Design drift 2026-05-26**：原 task 1.1 假設 local DB connection 可用；實際 `DATABASE_URL` host=`db:5432` 是 Zeabur 內部，本機解析失敗。改為 admin endpoint sweep（server-side in-process，require_admin gated, read-only）。詳見 proposal Proposed Solution 註記段。

- [x] 1.1 寫 admin endpoint `POST /admin/rrf/sweep` 在 `backend/app/api/admin/rrf_sweep.py`：require_admin gated，接收 body `{"candidates": [{"chunk":1.0,"description":N,"title":0.5}, ...], "show_id":"<uuid>", "mini_set_ids": ["b20","b21","b23","b15","b16","b17","b19"]}`（後兩欄位可預設 in code）。server 端對每組 weight monkey-patch `rag.RRF_WEIGHTS`、跑 dataset 對應 item 的 `retrieve_hybrid` + `chunk_recall_grouped` grader、restore 原 weights、collect per-item score + cross_episode_mean + deep_dive_mean。回 `{"baseline": {...}, "candidates": [...]}`。驗證 = 對 backend redeploy 後 curl 此 endpoint 帶 baseline weights，response 含 7 題每題 score + 兩 sub-set mean。Covers: RRF weight changes SHALL satisfy a non-regression gate
- [x] 1.2 backend 用 admin endpoint 跑 baseline weights (chunk=1.0/description=0.7/title=0.5) 對 mini-set 7 題，將 baseline 數字（cross_episode_recall_mean + deep_dive_recall_mean）落到 `docs/case-studies/rrf-cross-episode-weight-sweep-2026-05-26.md` 的 baseline 行。驗證 = sweep 回傳含 7 題每題 score + 兩 sub-set mean，case study 有「baseline」row 數字確定

## 2. Weight sweep + 選擇

- [x] 2.1 用 admin endpoint 跑 sweep 6 組候選 weights：description ∈ {0.85, 1.0, 1.2, 1.5}，title 固定 0.5、chunk 固定 1.0（另加兩組 sanity check：description=0.3 預期 cross_episode 退步、description=2.0 預期 deep_dive 過度 regression）。驗證 = sweep response 含 baseline + 6 候選共 7 組，每組有 cross_episode_recall_mean / deep_dive_recall_mean，case study 渲染成 markdown table 加 accepted-or-rejected 第三欄。Covers: RRF weight changes SHALL satisfy a non-regression gate
- [x] 2.2 依 gate 規則選最佳 accepted 候選。**2026-05-26 outcome：所有 6 候選 + 2 sanity 全 REJECT**（baseline 0.7 cross_ep=0.133；0.85/1.0/1.2 全部跟 baseline 同分 0.133 no gain；1.5/2.0 actively regress 到 0.067）→ **不修改 RRF_WEIGHTS**。RCA 寫進 `docs/case-studies/rrf-cross-episode-weight-sweep-2026-05-26.md`：根因是 description chunks 都是 episode-level `@0.0`，拉高 weight 把不同集的整集摘要推前，擠走正確集 transcript chunks。真實 lever 不是 weight 而是 episode pre-filter / chunk recovery。驗證 = case study 含完整 sweep table + per-item top5 證據 + 「不選任何候選」明確結論 + 真實 lever 建議

## 3. Negative finding 收尾（原 code change 取消）

> **Outcome shift 2026-05-26**：原 task 3.1 / 3.2 預期 ship weight 改動 + prod verify。實際 sweep 全 REJECT，不動 `RRF_WEIGHTS` → 跳過 ship 步驟，改寫 case study 推薦下一個 change。

- [x] 3.1 **不改** `backend/app/services/rag.py` 的 `RRF_WEIGHTS`（spec gate 保護生效）。確認 commit log 內無對 rag.py RRF_WEIGHTS 常數的改動。驗證 = `git log --oneline -- backend/app/services/rag.py` 在本 change 期間無修改 RRF_WEIGHTS 常數的 commit
- [x] 3.2 跳過 prod re-baseline（無 code change 不需重跑全 34 題）。在 case study「結論」section 標註：保留現有 baseline `chat-rag-baseline-2026-05-26-post-mt-fix.md` 為 reference 不動。驗證 = case study 含「不重跑全 34」明確說明 + 引用既有 baseline 為 unchanged reference

## 4. Follow-up change 提議

- [x] 4.1 在 case study 結論段落明確列出後續 change candidate（`retrieval-cross-episode-episode-prefilter` 或同類動 retrieval 架構的 change）+ 其 evidence 來源（本 change 的 RCA section）。驗證 = case study 至少 1 個「建議下一個 change」具名提議 + 解釋為何那個 lever 對 cross_episode 治本

## 5. Sanity tests（保留 — admin endpoint 自身仍有 ship 價值）

- [x] 5.1 新增 unit test `backend/tests/test_admin_rrf_sweep.py` 對 admin endpoint 做最小 smoke：require_admin gate / body schema 接收 / monkey-patch 確實 restore 原 RRF_WEIGHTS。驗證 = `pytest backend/tests/test_admin_rrf_sweep.py` 全綠
