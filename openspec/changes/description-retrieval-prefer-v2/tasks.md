## 1. SQL 改寫：description retrieval prefer-v2 — design D1 / D2

- [ ] 1.1 [spec: retrieve_descriptions prefers v2 when present] 改 `backend/app/services/rag.py` 的 `_DESC_RRF_SQL` semantic CTE WHERE 子句，加上 `(d.chunking_version = 2 OR (d.chunking_version = 1 AND d.episode_id NOT IN (sub-select v2 episodes for show)))`
- [ ] 1.2 [spec: retrieve_descriptions prefers v2 when present] `_DESC_RRF_SQL` lexical CTE WHERE 子句套用同 prefer-v2 邏輯
- [ ] 1.3 [spec: retrieve_descriptions prefers v2 when present] `_DESC_SEMANTIC_ONLY_SQL` 套用同 prefer-v2 WHERE
- [ ] 1.4 [spec: retrieve_descriptions prefers v2 when present] 三條 SQL 的 sub-select 用 share 同 show_id binding，無新 param 引入；確認 SQLAlchemy text() 仍能 parametrize
- [ ] 1.5 本機跑 `EXPLAIN ANALYZE` 對改後 SQL，確認規劃器選 hash semi-join（不是 nested loop on episode_description_chunks）

## 2. SQL 改寫：route_episodes DISTINCT episode + prefer-v2 — design D3

- [ ] 2.1 [spec: route_episodes returns distinct episode_ids] 改 `_ROUTE_EPISODES_SQL`：外層 SELECT 包 inner query，inner query 用 `DISTINCT ON (e.id) e.id, d.embedding <=> :qv AS dist`，外層 `ORDER BY dist ASC LIMIT :k`
- [ ] 2.2 [spec: route_episodes prefers v2 when present] inner query WHERE 加 prefer-v2 子句（同 1.1）
- [ ] 2.3 [spec: route_episodes returns distinct episode_ids] route_episodes() Python 端確認 result mapping 回的還是 episode_id list，無 signature 變動
- [ ] 2.4 本機 EXPLAIN ANALYZE：對 pilot show v2 共存場景，確認回 K 個不同 episode_id

## 3. 單元測試 — 對應 spec scenarios

- [ ] 3.1 新建 `backend/tests/test_description_retrieval_prefer_v2.py`，setup async test fixture with mock pgvector schema
- [ ] 3.2 [spec scenario: prefer-v2 hides v1 when v2 exists] Fixture：episode E1 有 v1+v2，呼叫 `retrieve_descriptions(show, ...)` 結果含 v2 hits、不含 E1 v1 hits
- [ ] 3.3 [spec scenario: v1 fallback when no v2 for episode] Fixture：episode E2 只有 v1，retrieve 結果含 E2 v1 hit（fallback 通）
- [ ] 3.4 [spec scenario: pure-v1 show unaffected] Fixture：show 完全沒 v2，retrieve 結果等同未改前（純 v1 pool）
- [ ] 3.5 [spec scenario: routing returns distinct episodes] Fixture：episode E1 有 v2 chunks ×10、E2 有 v1 ×1，`route_episodes(k=2)` 結果 = [E1, E2]（兩個 distinct）
- [ ] 3.6 [spec scenario: routing prefers v2 ranking] Fixture：E1 v2 與 E2 v1 各自接近 query，routing 用 v2 那 chunk 排序（不會被 E1 v1 干擾）
- [ ] 3.7 [spec scenario: empty v2 sub-select degenerates to v1] Pure-v1 fixture 跑 routing → behaviour = LIMIT 10 episodes by v1 cosine

## 4. Spec delta：推翻 chunking-version-coexistence D3 — design D4

- [ ] 4.1 [spec: rag-query/MODIFIED retrieve_hybrid pools v1 and v2] 在 `openspec/changes/description-retrieval-prefer-v2/specs/rag-query/spec.md` 用 MODIFIED 段更新 chunking-version-coexistence 留下的 requirement「retrieve_hybrid pools v1 and v2 description chunks together」，改成 prefer-v2 邏輯
- [ ] 4.2 docstring：在 rag.py SQL 改寫位置註明「chunking-version-coexistence D3 假設已被本 change 證偽，見 design.md D4」
- [ ] 4.3 不動 chunking-version-coexistence 已 archive 的內容（保留歷史紀錄）；只在本 change spec delta 留證據鏈

## 5. Phase 1 sanity（pre-deploy lever 驗證）

- [ ] 5.1 本機跑 `pytest backend/tests/test_description_retrieval_prefer_v2.py` 全綠
- [ ] 5.2 對 prod DB 開唯讀 query 跑 ranking simulation（不動 prod code）：用本 change 預期 WHERE 子句驗證 EP1 v2 chunk_index=2 確實能進 lexical top-50（rn ≤ 50）

## 6. 部署 + Phase 2 final eval — design D5 / D6

- [ ] 6.1 commit + push 整 change
- [ ] 6.2 Zeabur backend service redeploy
- [ ] 6.3 Prod smoke：`/shows/45fc.../search?q=節目名是怎麼來的` top-5 含 EP1 hit（手測 sanity）
- [ ] 6.4 Eval Phase preflight：跑 `.claude/skills/rag-eval-runner/SKILL.md` v2.0 preflight + canary 3
- [ ] 6.5 Eval Phase main run：完整 48Q with-judge run
- [ ] 6.6 Eval Phase variance：3 runs，計算 SD
- [ ] 6.7 寫 case study 補述：`docs/case-studies/r32-routing-regression-2026-05-11.md` 加 Phase 2 retry section
- [ ] 6.8 依 D6 判定：
   - Recall@5 ≥ 0.35 → ship + 進 r3-2-retrieval-fix Phase 2 rollout #2
   - [0.20, 0.35) → ship + 另起 `r3-4-embedding-model-swap`
   - < 0.20 → 不 ship 本 change，case study 紀錄結果

## 7. 收尾

- [ ] 7.1 更新 `docs/roadmap.md` + memory `project_pending_changes.md` 對應條目（雙寫）
- [ ] 7.2 release log 起草 entry（不 commit；等 user review）
- [ ] 7.3 `/spectra-archive description-retrieval-prefer-v2` — 在所有 ship 條件達成後執行
