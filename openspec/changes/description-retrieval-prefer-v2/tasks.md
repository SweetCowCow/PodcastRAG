## 1. SQL 改寫：description retrieval prefer-v2 — design D1 / D2

- [x] 1.1 [spec: retrieve_descriptions prefers v2 when present] 改 `backend/app/services/rag.py` 的 `_DESC_RRF_SQL` semantic CTE WHERE 子句，加上 `(d.chunking_version = 2 OR (d.chunking_version = 1 AND d.episode_id NOT IN (sub-select v2 episodes for show)))`
- [x] 1.2 [spec: retrieve_descriptions prefers v2 when present] `_DESC_RRF_SQL` lexical CTE WHERE 子句套用同 prefer-v2 邏輯
- [x] 1.3 [spec: retrieve_descriptions prefers v2 when present] `_DESC_SEMANTIC_ONLY_SQL` 套用同 prefer-v2 WHERE
- [x] 1.4 [spec: retrieve_descriptions prefers v2 when present] 三條 SQL 的 sub-select 用 share 同 show_id binding，無新 param 引入；確認 SQLAlchemy text() 仍能 parametrize
- [x] 1.5 本機跑 `EXPLAIN ANALYZE` 對改後 SQL，確認規劃器選 hash semi-join（不是 nested loop on episode_description_chunks）

## 2. SQL 改寫：route_episodes DISTINCT episode + prefer-v2 — design D3

- [x] 2.1 [spec: route_episodes returns distinct episode_ids] 改 `_ROUTE_EPISODES_SQL`：外層 SELECT 包 inner query，inner query 用 `DISTINCT ON (e.id) e.id, d.embedding <=> :qv AS dist`，外層 `ORDER BY dist ASC LIMIT :k`
- [x] 2.2 [spec: route_episodes prefers v2 when present] inner query WHERE 加 prefer-v2 子句（同 1.1）
- [x] 2.3 [spec: route_episodes returns distinct episode_ids] route_episodes() Python 端確認 result mapping 回的還是 episode_id list，無 signature 變動
- [x] 2.4 本機 EXPLAIN ANALYZE：對 pilot show v2 共存場景，確認回 K 個不同 episode_id

## 3. 單元測試 — 對應 spec scenarios

- [x] 3.1 新建 `backend/tests/test_description_retrieval_prefer_v2.py`，setup async test fixture with mock pgvector schema
- [x] 3.2 [spec scenario: prefer-v2 hides v1 when v2 exists] Fixture：episode E1 有 v1+v2，呼叫 `retrieve_descriptions(show, ...)` 結果含 v2 hits、不含 E1 v1 hits
- [x] 3.3 [spec scenario: v1 fallback when no v2 for episode] Fixture：episode E2 只有 v1，retrieve 結果含 E2 v1 hit（fallback 通）
- [x] 3.4 [spec scenario: pure-v1 show unaffected] Fixture：show 完全沒 v2，retrieve 結果等同未改前（純 v1 pool）
- [x] 3.5 [spec scenario: routing returns distinct episodes] Fixture：episode E1 有 v2 chunks ×10、E2 有 v1 ×1，`route_episodes(k=2)` 結果 = [E1, E2]（兩個 distinct）
- [x] 3.6 [spec scenario: routing prefers v2 ranking] Fixture：E1 v2 與 E2 v1 各自接近 query，routing 用 v2 那 chunk 排序（不會被 E1 v1 干擾）
- [x] 3.7 [spec scenario: empty v2 sub-select degenerates to v1] Pure-v1 fixture 跑 routing → behaviour = LIMIT 10 episodes by v1 cosine

## 4. Spec delta：推翻 chunking-version-coexistence D3 — design D4

- [x] 4.1 [spec: rag-query/MODIFIED retrieve_hybrid pools v1 and v2] 在 `openspec/changes/description-retrieval-prefer-v2/specs/rag-query/spec.md` 用 MODIFIED 段更新 chunking-version-coexistence 留下的 requirement「retrieve_hybrid pools v1 and v2 description chunks together」，改成 prefer-v2 邏輯
- [x] 4.2 docstring：在 rag.py SQL 改寫位置註明「chunking-version-coexistence D3 假設已被本 change 證偽，見 design.md D4」
- [x] 4.3 不動 chunking-version-coexistence 已 archive 的內容（保留歷史紀錄）；只在本 change spec delta 留證據鏈

## 5. Phase 1 sanity（pre-deploy lever 驗證）

- [x] 5.1 本機跑 `pytest backend/tests/test_description_retrieval_prefer_v2.py` 全綠
- [x] 5.2 對 prod DB 開唯讀 query 跑 ranking simulation（不動 prod code）：用本 change 預期 WHERE 子句驗證 EP1 v2 chunk_index=2 確實能進 lexical top-50（rn ≤ 50）

## 6. 部署 + Phase 2 final eval — design D5 / D6

- [x] 6.1 commit + push 整 change
- [x] 6.2 Zeabur backend service redeploy
- [x] 6.3 Prod smoke：EP1 沒進 q01 top-5（手測證實），但 retrieval pool 結構修了（regression 0.0952 → 0.1548 復原）
- [x] 6.4 Eval Phase preflight + canary：preflight 跑過，canary 跳過（沿用前面 5-arm 已建立的 metric sanity / variance baseline）
- [x] 6.5 Eval main run：result `backend/eval/results/eval-this-not-that-cool-20260512T054303Z.json`
- [x] 6.6 Variance：本輪只跑 1 run（變 SD 由前 5 arm 同 backend 同 dataset 推斷接受）
- [x] 6.7 case study 補述：見 `docs/case-studies/r32-routing-regression-2026-05-11.md` 末尾 Phase 2 retry section
- [x] 6.8 依 D6 兩分支判定：
   - Recall@5 = 0.1548 < 0.30 → **FAIL**
   - 動作：本 change 不 archive、不 rollout 曼報/壹加壹電台；開 `r3-4-embedding-model-swap` change（agent 並行起草中）
   - 例外：prefer-v2 code 本身 net positive（修了 regression + routing chunk-row bug + P95 latency -56%），保留 in prod 不 revert

## 7. 收尾

- [x] 7.1 更新 `docs/roadmap.md` + memory `project_pending_changes.md`（本 change FAIL gate 但保留 prod，等 r3-4 補尾）
- [ ] 7.2 release log 起草 entry — 推遲到 r3-4 ship 完一起 release（避免 v1.x release 連續多個沒過 R3.2 gate）
- [ ] 7.3 `/spectra-archive description-retrieval-prefer-v2` — 等 r3-4-embedding-model-swap ship 過 R3.2 gate 後一起 archive
