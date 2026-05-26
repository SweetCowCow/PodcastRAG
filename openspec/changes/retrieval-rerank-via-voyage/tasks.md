## 1. Voyage SDK + VOYAGE_API_KEY environment variable

- [x] 1.1 取得 Voyage AI 帳號 + API key（user 操作）；把 key 加到 `backend/.env` 為 `VOYAGE_API_KEY=...`。確認本地 `python -c "import os; from voyageai.client_async import AsyncClient; c=AsyncClient(api_key=os.environ['VOYAGE_API_KEY']); print('client OK')"` 跑得起來。驗證 = local 印 `client OK` + key 不出現在 chat（用 memory `feedback_secret_handoff_via_file.md` SOP）
- [x] 1.2 加 `voyageai>=0.4` 到 `backend/requirements.txt`，pin 一個確定版本（譬如 `voyageai==0.4.4`）避免 SDK breaking change。本地 `pip install -r requirements.txt` 跑成功。驗證 = `pip show voyageai` 顯示 installed version match pin
- [x] 1.3 `backend/.env.example` 加 `VOYAGE_API_KEY=` 範例條目（空值），讓後續開發者知道要設。驗證 = grep 到 entry

## 2. voyage_rerank function in rag_rerank module

- [x] 2.1 在 `backend/app/services/rag_rerank.py` 新增 `async def voyage_rerank(question: str, chunks: list[dict], k: int, *, client, model: str = "rerank-2.5", timeout_s: float = 3.0) -> tuple[list[dict], bool]`：(a) 用 voyageai AsyncClient call `await client.rerank(query=question, documents=[c.get("text","") for c in chunks], model=model, top_k=k)`；(b) 從回傳 results 取 `index` + 對應 chunks 列表；(c) timeout / exception → log warning + 回 `(chunks[:k], False)`；(d) 解析正常但全是未知 index → 同上 fallback；(e) 部分未知 → 已知 ordering + 用原 RRF 回填到 k 個。驗證 = `pytest backend/tests/test_voyage_rerank.py -v` 5 case 全綠
- [x] 2.2 新增 `backend/tests/test_voyage_rerank.py` 5 case（mock voyageai client，不打外網）：(a) `test_voyage_happy_path` — mock 回 index list 順序 → 輸出對 (b) `test_voyage_timeout_fallback` — mock raise asyncio.TimeoutError → 回 `(chunks[:k], False)` (c) `test_voyage_api_error_fallback` — mock raise generic Exception → 同上 (d) `test_voyage_unknown_index_dropped` — mock 回含越界 index → 略過 (e) `test_voyage_backfill_when_short` — mock 只回 2 個 valid index（k=5）→ 剩 3 個從 chunks 原順序補。驗證 = `pytest backend/tests/test_voyage_rerank.py -v` 5 case 全綠

## 3. _search_with_topic_prefilter — Top-N expand to 30 candidates + Voyage rerank-2.5 model selection

- [x] 3.1 修改 `backend/app/services/chat_agent/tools.py` `_search_with_topic_prefilter`：(a) prefilter 命中時 `retrieve_hybrid` k 從 `inp.k` 改 `30`；(b) 建 voyageai AsyncClient（讀 `os.environ.get("VOYAGE_API_KEY")`，若無 key → log warning + skip rerank）；(c) call `voyage_rerank(query, chunks, k=inp.k)` 拿 `(final_chunks, applied)`；(d) envelope `rerank_applied` 帶 applied 實際值、`rerank_input_count` 帶 `len(top_n_chunks)`；(e) empty-candidate fallback 路徑不變（applied=False, count=0）。驗證 = `python -c "from app.services.chat_agent.tools import _search_with_topic_prefilter; import inspect; src=inspect.getsource(_search_with_topic_prefilter); assert 'k=30' in src and 'voyage_rerank' in src and 'rerank_applied' in src"` 印 OK。Covers: search_with_topic_prefilter SHALL pre-scope retrieval to topic-matching episodes (MODIFIED — enable Voyage rerank stage)
- [x] 3.2 改 `backend/tests/test_chat_agent_topic_prefilter_rerank.py`：把上一個 change 改為 noop 的 test 6 case 重啟「rerank-applied 場景」：(a) `test_prefilter_calls_retrieve_with_k30` — 驗 retrieve_hybrid k=30 (b) `test_prefilter_calls_voyage_rerank` — mock voyage_rerank 被 call，args 含 query + 30 chunks (c) `test_envelope_rerank_applied_true_on_success` (d) `test_envelope_rerank_applied_false_on_failure` — mock voyage 回 (chunks[:k], False) (e) `test_empty_candidate_skips_rerank`（保留既有） (f) `test_envelope_compatibility`（保留既有）。驗證 = `pytest backend/tests/test_chat_agent_topic_prefilter_rerank.py -v` 6 case 全綠 + 既有 `test_chat_agent_topic_prefilter.py` 不破壞

## 4. Prod 部署 + smoke + eval — rerank documents payload uses chunk text

- [ ] 4.1 Zeabur 4 service env（backend / worker / dispatcher / beat）都設 `VOYAGE_API_KEY`（per memory `feedback_zeabur_variable_create_dumps_env.md` 用 `variable update -k` redirect stdout 避免印 key）。驗證 = `zeabur variable list --id <svc> --env-id <env>` 看到 entry（key value 不印出 chat）
- [ ] 4.2 push commit 觸發 Zeabur build，per memory `feedback_zeabur_deploy_monitor_pattern.md` 用 Monitor 工具等 RUNNING。驗證 = Monitor 收到 `<commit>: RUNNING` 事件
- [ ] 4.3 Smoke：refresh e2e session，對 b21 query `?debug_trace=true` → 印 envelope `rerank_applied / rerank_input_count` + tool latency_ms。Gate：`rerank_applied=true`、`rerank_input_count=30`、tool latency_ms < 2000。驗證 = jq 印出三個值都符合
- [ ] 4.4 跑 8 題 subset eval（b20/b21/b22/b23/b29/mt02/mt03/mt04）對 baseline 0.244：用 `backend/scripts/run_chat_agent_eval_v2.py --filter-ids b20,b21,b22,b23,b29,mt02,mt03,mt04`。case study `docs/case-studies/retrieval-rerank-via-voyage-<date>.md` 含：(a) cross_episode chunk_recall per-item table（baseline vs new）(b) factual_correctness 對比 (c) prefilter path p95 latency from `stage_timings` (d) rerank_applied 比率。Gate：cross_episode mean ≥ 0.40 且 factual ≥ 0.80 且 p95 < 2.0s → success。驗證 = case study 含 3 gate 明確 PASS/FAIL
- [ ] 4.5 結論判讀（依 gate 結果三選一）：**PASS** → archive；**PARTIAL**（chunk_recall 上升但未達 0.40 或 latency > 2s）→ 標 partial，propose follow-up（譬如 N=50 或加 metadata 進 doc）；**REGRESS**（chunk_recall < 0.244 或 factual < 0.80）→ revert commit + 寫 negative finding + 評估下個 lever（Cohere 或自架）。驗證 = case study 結論段三個路徑明確標示

## 5. 觀測 hook

- [ ] 5.1 確認 prod debug_trace 對 cross_episode query 在 `tool_calls[].result_full` 內帶 `rerank_applied=true` + `rerank_input_count=30` 給未來 RCA / cost monitoring 用。驗證 = prod curl 一題 cross_episode `?debug_trace=true` + `jq '.tool_calls[] | select(.name=="search_with_topic_prefilter") | .result_full | fromjson | {rerank_applied, rerank_input_count}'` 印出兩個 field 都非預設值（applied=true, count=30）
