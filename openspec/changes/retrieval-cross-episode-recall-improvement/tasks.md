## 1. Admin sweep endpoint + baseline 量測

> **Design drift 2026-05-26**：原 task 1.1 假設 local DB connection 可用；實際 `DATABASE_URL` host=`db:5432` 是 Zeabur 內部，本機解析失敗。改為 admin endpoint sweep（server-side in-process，require_admin gated, read-only）。詳見 proposal Proposed Solution 註記段。

- [ ] 1.1 寫 admin endpoint `POST /admin/rrf/sweep` 在 `backend/app/api/admin/rrf_sweep.py`：require_admin gated，接收 body `{"candidates": [{"chunk":1.0,"description":N,"title":0.5}, ...], "show_id":"<uuid>", "mini_set_ids": ["b20","b21","b23","b15","b16","b17","b19"]}`（後兩欄位可預設 in code）。server 端對每組 weight monkey-patch `rag.RRF_WEIGHTS`、跑 dataset 對應 item 的 `retrieve_hybrid` + `chunk_recall_grouped` grader、restore 原 weights、collect per-item score + cross_episode_mean + deep_dive_mean。回 `{"baseline": {...}, "candidates": [...]}`。驗證 = 對 backend redeploy 後 curl 此 endpoint 帶 baseline weights，response 含 7 題每題 score + 兩 sub-set mean。Covers: RRF weight changes SHALL satisfy a non-regression gate
- [ ] 1.2 backend 用 admin endpoint 跑 baseline weights (chunk=1.0/description=0.7/title=0.5) 對 mini-set 7 題，將 baseline 數字（cross_episode_recall_mean + deep_dive_recall_mean）落到 `docs/case-studies/rrf-cross-episode-weight-sweep-2026-05-26.md` 的 baseline 行。驗證 = sweep 回傳含 7 題每題 score + 兩 sub-set mean，case study 有「baseline」row 數字確定

## 2. Weight sweep + 選擇

- [ ] 2.1 用 admin endpoint 跑 sweep 6 組候選 weights：description ∈ {0.85, 1.0, 1.2, 1.5}，title 固定 0.5、chunk 固定 1.0（另加兩組 sanity check：description=0.3 預期 cross_episode 退步、description=2.0 預期 deep_dive 過度 regression）。驗證 = sweep response 含 baseline + 6 候選共 7 組，每組有 cross_episode_recall_mean / deep_dive_recall_mean，case study 渲染成 markdown table 加 accepted-or-rejected 第三欄。Covers: RRF weight changes SHALL satisfy a non-regression gate
- [ ] 2.2 依 gate 規則選最佳 accepted 候選（cross_episode_recall_mean 最高 + deep_dive_recall_mean 不退超過 0.05）。把選擇邏輯（為何選 X 不選 Y）+ baseline 對比寫進 case study「選擇」section。驗證 = case study 有「選定 weights」明確一行（如 `RRF_WEIGHTS = {"chunk": 1.0, "description": 1.2, "title": 0.5}`） + 選定 cross_episode gain 數字 + 選定 deep_dive 差異數字 + 至少一句說明為何不選次佳候選

## 3. Code change + prod 驗證

- [ ] 3.1 在 `backend/app/services/rag.py` 把 `RRF_WEIGHTS` 常數改成 task 2.2 選定的數字 + 改 inline 註解描述新 baseline 來源（pointing 到 case study 路徑）。驗證 = `grep -n "RRF_WEIGHTS" backend/app/services/rag.py` 顯示新值 + 註解含 `docs/case-studies/rrf-cross-episode-weight-sweep-2026-05-26.md` 字串
- [ ] 3.2 backend redeploy 到 Zeabur 後跑全 v2 triage 34 題 (`b01...b30 + mt01...mt04`)，驗證 cross_episode design_type 的 chunk_recall_grouped mean ≥ task 2.2 預期 gain，deep_dive design_type 不退超過 0.05。驗證 = 新 triage JSON 對比 `/tmp/v2-triage-27.json` 的 aggregate.by_design_type，把對比表落到 case study 的「Prod verification」section。Covers: Semantic search endpoint returns ranked chunks

## 4. Sanity tests

- [ ] 4.1 新增 unit test `backend/tests/test_rag_rrf_weights.py` 確認 `RRF_WEIGHTS` 是 dict + 三個 key (`chunk`/`description`/`title`) 都存在且為 float 且皆 > 0。驗證 = `pytest backend/tests/test_rag_rrf_weights.py` 全綠 + 對未來改 weight 時防呆（譬如改成 dict 缺 key 就會 fail）
- [ ] 4.2 跑既有 `backend/tests/test_rag_rrf.py`（如果存在）確認新 weights 不破壞 existing RRF unit tests。驗證 = `pytest backend/tests/test_rag_rrf.py` 全綠（若 test 內 hardcode 舊 0.7/0.5 數字則更新成 import RRF_WEIGHTS）
