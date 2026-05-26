## 1. Diagnostic gate before implementation（GO/NO-GO）

- [ ] 1.1 新增 admin endpoint `POST /admin/diagnose/prefilter-rank` (`backend/app/api/admin/diagnose_prefilter.py`) + 本地 driver `backend/scripts/diagnose_prefilter_rank.py`。Endpoint contract：(a) body `{ "mini_set_ids": ["b20","b21","b23"], "top_n": 100 }`；(b) 對每題：embed question → `rag.retrieve_hybrid(query, episode_id_filter=<expected_episode_uuids_must>, k=top_n)`（用 dataset 的 `expected_episode_uuids_must` 當「完美 prefilter」模擬 — 排除 topic 抽取雜訊）→ 對回傳的 chunk list 配對 `ground_truth_chunk_ids_must` + `ground_truth_chunk_ids_either` (±10s 視窗匹配，重用 rrf_sweep 的 `_chunk_in_retrieved` 邏輯) → 算每個 GT chunk 在 top-5/20/50/100 的 rank (1-based, None 表示沒在 top_n 內)；(c) require_admin gate；(d) 回 JSON `{ "items": [{"item_id","top_n","gt_ranks":[{"gt_chunk_id","rank","cutoff_in":"top-5|top-20|top-50|top-100|miss"}],"gt_total"}] }`。Driver 用 e2e cookie hit endpoint，落地到 `/tmp/diagnose-prefilter-rank.json`。驗證 = `python -m backend.scripts.diagnose_prefilter_rank --mini-set-ids b20,b21,b23 --top-n 100 --output /tmp/diagnose-prefilter-rank.json` 跑完且 JSON 內 3 題各含 gt_ranks 陣列。Covers: Rerank reorders top-20 candidates and returns top-k（pre-condition validation）
- [ ] 1.2 GO/NO-GO 判讀：將 1.1 結果 append 進 `docs/case-studies/retrieval-cross-episode-chunk-recovery-2026-05-26.md` 的「Diagnostic」段。判讀規則：
  - **GO**：b20/b21/b23 至少 2 題 GT 全部 chunk_ids 落在 top-20（或 N 上調到 50 內）→ 繼續 task 2
  - **NO-GO**：3 題中 ≥ 2 題 GT chunk_ids 不在 top-50 → mechanism 假設錯，停下來把結果丟給 user 拍板要不要 pivot 到 chunk-level overlap merging（方向 D），不再執行後續 task。

  驗證 = case study 含 GO/NO-GO 結論段 + 明確標註下一步動作

## 2. rerank module — use gemini-2.5-flash-lite for LLM rerank, with rerank prompt schema design

- [ ] 2.1 新增 `backend/app/services/rag/rerank.py`，提供 `async def llm_rerank(question: str, chunks: list[dict], k: int, *, timeout_s: float = 1.5) -> tuple[list[dict], bool]`：(a) 用既有 `app/services/llm.py` client，model `gemini-2.5-flash-lite`；(b) prompt 帶 question + 每個 chunk 的 `chunk_id` + text 前 200 字；(c) 要求 LLM 回 JSON `{"ranked_chunk_ids": [...]}`，response_format json_object；(d) 解析 JSON 失敗 / timeout / 5xx → 回傳 `(chunks[:k], False)`；(e) 解析成功 → 按 `ranked_chunk_ids` 順序取已知 chunk，未知 ID 丟棄，缺額用原順序回填，回傳 `(reordered[:k], True)`。驗證 = `pytest backend/tests/test_rerank.py -v` 5 case 全綠（happy path / timeout fallback / malformed JSON fallback / unknown chunk_id 過濾 / 缺額回填）
- [ ] 2.2 新增 `backend/tests/test_rerank.py` 5 case：(a) `test_rerank_happy_path` — mock LLM 回正確 JSON，驗證輸出順序 (b) `test_rerank_timeout_fallback` — mock LLM raise asyncio.TimeoutError，驗證回 (chunks[:k], False) (c) `test_rerank_malformed_json_fallback` — mock LLM 回 "not json"，驗證回 fallback (d) `test_rerank_unknown_chunk_ids_dropped` — mock LLM 回含未知 ID，驗證輸出只含已知 ID (e) `test_rerank_backfill_when_short` — mock LLM 只回 2 個 valid ID（k=5），驗證剩 3 個從原 chunks 順序補。驗證 = `pytest backend/tests/test_rerank.py -v` 5 case 全綠。Covers: Rerank failure falls back to original RRF order + Rerank output partially unknown chunk_ids are filtered and back-filled

## 3. Wire rerank into search_with_topic_prefilter — top-N expand to 20 candidates; limit rerank to search_with_topic_prefilter path

- [ ] 3.1 修改 `backend/app/services/chat_agent/tools.py` `_search_with_topic_prefilter`：(a) prefilter path 的 `retrieve_hybrid` k 從 `inp.k` 改 `20`；(b) call `rerank.llm_rerank(query, top_n_chunks, k=inp.k)` 拿 `(final_chunks, applied)`；(c) envelope 新增 `rerank_applied: bool` + `rerank_input_count: int` 兩個 field；(d) empty-candidate fallback path 保持 `k=inp.k` 不擴展、`rerank_applied=False`、`rerank_input_count=0`。驗證 = `python -c "from app.services.chat_agent.tools import _search_with_topic_prefilter; import inspect; src=inspect.getsource(_search_with_topic_prefilter); assert 'k=20' in src and 'rerank_applied' in src and 'rerank_input_count' in src"` 印 OK。Covers: search_with_topic_prefilter SHALL pre-scope retrieval to topic-matching episodes（MODIFIED — 增加 rerank pipeline）
- [ ] 3.2 新增 `backend/tests/test_chat_agent_topic_prefilter_rerank.py` 6 case：(a) `test_prefilter_calls_retrieve_with_k20` — 驗證 retrieve_hybrid call 帶 k=20 (b) `test_prefilter_calls_rerank_after_retrieve` — mock rerank 被 call，args 包含 query + 20 chunks (c) `test_envelope_has_rerank_fields` — 驗證 envelope 含 `rerank_applied` + `rerank_input_count` (d) `test_empty_candidate_skips_rerank` — fallback path 不 call rerank、envelope `rerank_applied=False` + `rerank_input_count=0` (e) `test_rerank_failure_returns_rrf_top_k` — mock rerank 回 (chunks[:k], False)，驗證 tool 回原 RRF 順序 (f) `test_envelope_compatibility_with_old_consumers` — 舊 envelope field（chunks / prefilter_episode_count / fallback_to_full_pool）仍存在不變。驗證 = `pytest backend/tests/test_chat_agent_topic_prefilter_rerank.py -v` 6 case 全綠 + 既有 `test_chat_agent_topic_prefilter.py` 仍 pass。Covers: Envelope fields are always populated + Rerank reorders top-20 candidates and returns top-k

## 4. Prod 驗證 + case study

- [ ] 4.1 backend redeploy 到 Zeabur（純 Python 變更，無 migration），等 RUNNING + smoke `/health` 200 + `?debug_trace=true` 對 b20 query 看 tool_calls 含 `rerank_applied=true` + `rerank_input_count=20`。驗證 = `npx zeabur deployment list --service-id 69eb10360da29f05f49a4b0b | grep <commit>` 顯示 RUNNING + smoke curl 印出 envelope 兩個新 field
- [ ] 4.2 跑 8 題 subset eval（b20/b21/b22/b23/b29/mt02/mt03/mt04）對比 baseline 0.244：
  - 用 `backend/scripts/run_chat_agent_eval_v2.py --filter-ids b20,b21,b22,b23,b29,mt02,mt03,mt04`
  - case study `docs/case-studies/retrieval-cross-episode-chunk-recovery-2026-05-26.md` 含：(a) cross_episode chunk_recall_grouped per-item table（baseline vs new）(b) factual_correctness mean 對比 (c) prefilter path p95 latency（從 debug_trace stage_timings 量）(d) rerank_applied 比率 (e) 至少 1 個 before/after 排序變化的具體範例

  **Gate**：cross_episode chunk_recall mean ≥ 0.40 且 factual mean ≥ 0.80 且 p95 latency < 2.5s → success；否則 revert + 寫 negative finding case study。驗證 = case study 含 3 個 gate 的明確 PASS/FAIL 判定

- [ ] 4.3 結論判讀（依 gate 結果三選一）：
  - **PASS**：metric 達標 → 進 archive 流程
  - **PARTIAL**（chunk_recall 上升但未達 0.40，或 latency 超 2.5s）：case study 標記 partial，propose follow-up 處理剩餘 gap（譬如改 cross-encoder 或調 N）
  - **REGRESS**（chunk_recall < 0.244 或 factual < 0.80）：revert commit + 改 case study 為 negative finding + 提議下一個 lever（譬如方向 D chunk overlap merging）

  驗證 = case study 結論段三個明確判讀路徑都有寫；revert 路徑包含 git revert 指令 + 通知 user

## 5. 觀測 hook

- [ ] 5.1 確認 prefilter path debug_trace 內 `tool_calls[].result_full` 對 `search_with_topic_prefilter` 帶 `rerank_applied` / `rerank_input_count` 兩個 field 給未來 RCA 用。驗證 = prod curl 一題 cross_episode 帶 debug_trace + `jq '.tool_calls[] | select(.name=="search_with_topic_prefilter") | .result_full | fromjson | {rerank_applied, rerank_input_count}'` 印出兩個 field 非 null
