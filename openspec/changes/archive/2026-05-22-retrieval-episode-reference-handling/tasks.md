## 1. 新建 episode-reference 偵測 helper

- [x] 1.0 實作 spec requirement「Public search endpoint SHALL detect episode references in the query and filter retrieval to those episodes」§ helper 部分。
- [x] 1.1 新建 `backend/app/services/episode_ref.py`，定義 async function `extract_episode_ids_from_query(db: AsyncSession, show_id: uuid.UUID, query: str) -> list[uuid.UUID]`：用 `re.findall(r"EP\s*(\d+)", query, flags=re.IGNORECASE)` 抽 number list；依序去重；對每個 number N 跑 `SELECT id FROM episodes WHERE show_id = :sid AND title ~ ('^EP' || :n || '(\D|$)')`（PostgreSQL 正則）；命中存進 ordered list；missed 的 number `logger.warning("episode_ref: number EP%s not found in show %s", n, show_id)`。Return ordered UUID list。

## 2. 接進 public search endpoint

- [x] 2.0 實作 spec requirement「Public search endpoint SHALL detect episode references in the query and filter retrieval to those episodes」§ endpoint wiring 部分。
- [x] 2.1 改 `backend/app/api/query.py` 的 `public_search_show`：在 `query_embedding` 取完後、`routed_eps` 計算後，呼 `await extract_episode_ids_from_query(db, show_id, payload.question)`；若 result 非空，把它賦值給 `routed_eps`（override）並 `logger.info("episode_ref: filtered to %d episode(s) from query", len(result))`。`retrieve_hybrid` 該行不動，仍傳 `episode_id_filter=routed_eps`。

## 3. Unit tests

- [x] 3.1 新建 `backend/tests/test_episode_ref.py` 涵蓋 5 個 spec scenario：
  - (a) single EP ref：mock db 回 EP134 UUID；query="EP134 講什麼" → list[EP134_uuid]
  - (b) multi EP ref：query="比較 EP134 跟 EP143" → list[EP134, EP143] 保序
  - (c) no EP ref：query="歌單那幾集" → []
  - (d) non-existent EP999：mock db 回 empty → [] + caplog 含 warning
  - (e) boundary disambiguation：mock db 回 EP1 only（不 match EP143）→ list[EP1_uuid]。SQL 用 `^EP1(\D|$)` 邊界
- [x] 3.2 跑 `pytest backend/tests/test_episode_ref.py -v` 全綠；跑既有 `test_chat_agent_loop.py` / `test_chat_agent_multi_turn.py` / `test_chat_agent_telemetry.py` / `test_chat_tool_error_isolation.py` / `test_agent_result_mapper.py` / `test_eval_runner_nested_recall.py` 確認無 regression。

## 4. Prod smoke + Recall baseline 重跑

- [x] 4.1 commit + push；等 Zeabur build RUNNING（用 `npx zeabur deployment list --service-id 69eb10360da29f05f49a4b0b` 確認最新 commit RUNNING）。
- [x] 4.2 用 backdoor session（per `reference_e2e_backdoor.md` SOP）取 prod cookie；對 prod 直打 `POST /shows/{id}/search` query="迪拉胖在 EP134 講什麼" 看 `results[]` 的 `episode_title` 全部含「EP134」字眼。
- [x] 4.3 用 backdoor session nohup 跑 `python3 -u backend/scripts/run_chat_agent_eval.py --dataset backend/eval/datasets/extended-multi-turn-40.json ... --label retrieval-ep-ref-<date>`；驗 `aggregate.recall_at_k_mean ≥ 0.40` + b14/b22/mt02 t1/mt03 t1/mt04 t1 個別 recall 從 0 變 ≥ 0.5。
- [x] 4.4 append 一行到 `docs/runbooks/eval-metrics-log.md`：dataset=multi-turn-40 v2、Recall 升幅、per-turn deltas、change name。
- [x] 4.5 若 Recall < 0.40 → STOP，回頭看是 helper 沒命中、還是 SQL regex 跑出範圍、或 endpoint 沒接好。Trace 用 `?debug_trace=true` + chat agent endpoint 跑同 query 對照。

## 5. Archive

- [x] 5.1 spectra-archive 收尾（sync spec to main + delete in-progress dir）。
- [x] 5.2 在 release log 起草 entry：tag=enhancement / fix（你看怎麼分），標題「Chat / 語意搜尋對「EP X」題型撈得到正確段落了」，描述 (a) baseline 0.2267 → 跑後實測 (b) 修法 = endpoint 端 EP-ref 偵測 + episode_id filter (c) chat agent path 不變、純 search endpoint fix。
- [x] 5.3 更新 `project_pending_changes.md` 反映已 archive；下一條 follow-up 排序前移。
