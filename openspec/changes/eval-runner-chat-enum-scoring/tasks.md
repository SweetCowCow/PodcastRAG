## 1. Runner 增 chat endpoint helper + 計分 union（落實 `Recall@K and MRR are computed per query against ground-truth chunks` MODIFIED + `Enumeration items carry chat-side diagnostic fields in per-item JSON output` + `Chat endpoint failures fail-open with empty episode set`）

- [x] 1.1 在 `backend/eval/runners/run.py` 新增 `_retrieve_chat_enumeration(backend_url, show_id, question, token) -> tuple[list[str], int | None]` 函式，落實 `Chat endpoint failures fail-open with empty episode set`：先 `GET /me` 拿 `csrf_token`（CSRF 拿不到回 `([], None)` + 列一次 startup warning，後續 enumeration 全 degenerate to search-only）；接著 `POST /shows/{show_id}/query` body `{"mode":"chat","question":<q>,"messages":[]}` 帶 `Cookie: session_id=<token>` + `X-CSRF-Token: <csrf>`；解析 `enumeration_episodes`（缺欄位回 `([], 0)` 表示 chat path 沒分類為 enum）；所有 exception / 5xx / timeout 路徑回 `([], None)` + stderr warning 含 item id + http status
- [x] 1.2 修改 `run.py` enumeration 分支落實 `Recall@K and MRR are computed per query against ground-truth chunks` MODIFIED enumeration 子段：原本 `retrieved_eps = _to_episode_ids(chunk_ids)` 改成 `retrieved_eps = set(_to_episode_ids(chunk_ids)) | set(chat_eps)`，其中 `chat_eps, chat_total = _retrieve_chat_enumeration(...)`。`episode_set_recall(retrieved_eps_union, expected_eps)` 用 union；同時計算 `episode_set_recall_chat_only`（只用 chat_eps，chat 失敗時為 None；chat 成功但 0 match 為 0.0）落實 `Enumeration items carry chat-side diagnostic fields in per-item JSON output`
- [x] 1.3 修改 per-item JSON 輸出：enumeration item 多塞 `enumeration_episodes_count: int`（chat 失敗時 0）+ `episode_set_recall_chat_only: float | None` 兩個欄位。Chunk_id / open_set_lenient 不動
- [x] 1.4 確認非 enumeration 分支**沒有任何 chat call**：`eval_mode in ("chunk_id", "open_set_lenient")` 跳過 chat helper，cost / 行為 byte-identical 到 r3-3-chat-enum-grounding baseline

## 2. 測試（落實 `Chat endpoint failures fail-open with empty episode set` + 三個 fail-open scenarios + diagnostic field 必填）

- [x] 2.1 新增 `backend/tests/test_runner_chat_enumeration.py`：(a) `test_chat_enumeration_helper_success`（mock requests.post 回 200 + valid body → 驗回 `(list of episode_ids, total int)`）；(b) `test_chat_enumeration_helper_5xx_returns_empty`（mock 回 503 → 驗回 `([], None)` + stderr 含 warning）；(c) `test_chat_enumeration_helper_no_csrf_returns_empty`（mock `/me` 回 200 但 body 無 csrf_token → 驗 `([], None)`）；(d) `test_chat_enumeration_helper_missing_field_returns_empty`（mock `/query` 回 200 但 body 無 enumeration_episodes → 驗 `([], 0)` 注意 total=0 不是 None）；(e) `test_chat_enumeration_helper_timeout_returns_empty`（mock raise `requests.Timeout` → 驗 `([], None)` 不 propagate）
- [x] 2.2 同檔加 (f) `test_enumeration_union_scoring_combines_search_and_chat`：mock `_retrieve` 回 search chunks → search eps = `{ep-A, ep-X}`；mock `_retrieve_chat_enumeration` 回 `({ep-A, ep-B, ep-C, ep-D}, 4)`；expected = `{ep-A..ep-E}` 5 集；assert 最終 `episode_set_recall == 0.8`、`episode_set_recall_chat_only == 0.8`（4/5 chat 命中 expected）
- [x] 2.3 同檔加 (g) `test_non_enumeration_items_skip_chat_call`：mock `_retrieve_chat_enumeration` 並 assert 對 eval_mode=chunk_id 的 item **沒被呼叫過** (call_count == 0)

## 3. Prod 驗證

- [ ] 3.1 commit + push（commit message 列改動 + 對應 spec 的 modified/added 區塊）；無 frontend 變更不用等 frontend build
- [ ] 3.2 對 prod 重跑 R1.2 eval（n=30）：對比 r3-3-chat-enum-grounding 那輪 `Episode Set Recall (enumeration, n=2) = 0.1867`，預期 q25 從 0.04 → ≥ 0.85、q26 從 0.333 → ≥ 0.5、aggregate ≥ 0.7（這條代表 chat enumeration_episodes 真的被納入了）
- [ ] 3.3 對比 `Recall@5 (chunk, episode, n=28) = 0.86` byte-identical（驗 chunk_id / open_set_lenient 不受影響）

## 4. 收尾

- [ ] 4.1 補 release log entry（v1.7 內，date 2026-05-16，slug `eval-runner-chat-enum-scoring`，tag `enhancement`，user-perspective 講「眼睛沒看到的：之前 eval 沒有把 chat 列舉結果算進去，這次補上，q25 歌單題從 0.04 跳到 0.92+ — 系統表現實際上比之前的數字好得多」）
- [ ] 4.2 更新 `docs/case-studies/r33-metadata-filter.md` 補 Stage 9：用真實 eval 數字證明 r3-3-chat-enum-grounding 的 lift（q25 / q26 跳幅）
- [ ] 4.3 同步 memory `project_pending_followups.md`：把 r3-3-chat-enum-grounding 那段的 "衍生 follow-up：eval-runner-chat-enum-scoring" 標完成
- [ ] 4.4 `/spectra-archive eval-runner-chat-enum-scoring`
