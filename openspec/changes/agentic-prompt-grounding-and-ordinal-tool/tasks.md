## 1. Implement `list_episodes` tool + backend helper

- [x] 1.1 In `backend/app/services/episode_finders.py`, add async function `find_episodes_by_recency(db, show_id, *, n=5, order='newest', topic=None, year_start=None, year_end=None)` that returns `{episodes: list[EpisodeRef], n_total_matched: int}`. Reuse `_row_to_episode_ref` for shape consistency.
- [x] 1.2 Implement the SQL inside `find_episodes_by_recency`: SELECT episode columns FROM episodes WHERE show_id = :show_id; `AND` clause for `EXTRACT(YEAR FROM published_at AT TIME ZONE 'Asia/Taipei') BETWEEN :year_start AND :year_end` when both year params are provided; topic filter via `EXISTS (SELECT 1 FROM episode_description_chunks ... tsquery(:topic))` reusing the same `simple_cjk` analyzer pattern from `find_episodes_by_topic`; `ORDER BY published_at DESC NULLS LAST` for `order='newest'` else `ASC NULLS LAST`; `LIMIT :n`. Run a separate COUNT(*) query (or use a window function) to populate `n_total_matched` against the same filters without LIMIT.
- [x] 1.3 In `backend/app/services/chat_agent/tools.py`, define a Pydantic `BaseModel` named `ListEpisodesInput` with the field set from design D1: `show_id: UUID` (required), `n: int = Field(5, ge=1, le=20)`, `order: Literal['newest', 'oldest'] = 'newest'`, `topic: str | None = None`, `year_start: int | None = Field(None, ge=2000, le=2100)`, `year_end: int | None = Field(None, ge=2000, le=2100)`. Add a model validator that raises `ValueError("year_start must be <= year_end")` when both years are provided and out of order.
- [x] 1.4 In the same file, implement async wrapper `_list_episodes(inp: ListEpisodesInput, ctx: ToolContext) -> dict` that calls `episode_finders.find_episodes_by_recency(...)` with the unpacked input fields and returns a dict `{"episodes": [...], "n_returned": <len>, "n_total_matched": <count>}`. The `episodes` list SHALL serialise EpisodeRef via the same path the existing finder wrappers use (`_row_to_episode_ref` -> dict).
- [x] 1.5 Register the new tool by appending `ToolSpec(name="list_episodes", description="...", input_schema=ListEpisodesInput, func=_list_episodes)` to the `TOOLS` list in `tools.py`. The `description` SHALL explain: "列出節目集數，支援依發布時間排序（最新 / 最舊）+ 可選 topic / year_range filter。適合『最新 N 集 / 最舊 N 集 / 2024 年最後一集歌單』這類 recency-driven query。"
- [x] 1.6 In `_writeback_enumeration_anchor` (same file), confirm the function already iterates `result.get("episodes")` and treats `episode_id` UUIDs as enumeration anchors. The new `list_episodes` tool returns the same `episodes` key shape, so write-back SHALL work without code change. Verify by code inspection (no behavioral test in this task — covered by task 2.3).

## 2. Cover the new tool with pytest

- [x] 2.1 Create `backend/tests/test_list_episodes_recency.py`. Use the same conftest helpers (`db_session`, fixture creating a pytest show + N episodes with explicit `published_at` and description chunks).
- [x] 2.2 Add `test_default_n_newest_order`: seed 5 episodes spanning 2024-01-01..2025-05-01, call `find_episodes_by_recency(db, show_id, n=3)`, assert returned 3 episodes have descending `published_at` and `n_total_matched == 5`.
- [x] 2.3 Add `test_order_oldest`: same seed, call with `order='oldest', n=2`, assert ASC order + correct episodes.
- [x] 2.4 Add `test_topic_filter`: seed 3 episodes mentioning "AI" in description, 2 not; call with `topic='AI'`, assert `episodes` only contain the 3 + `n_total_matched == 3`.
- [x] 2.5 Add `test_year_range_single_year`: seed episodes in 2023, 2024, 2025; call with `year_start=2024, year_end=2024`, assert only 2024 episodes returned.
- [x] 2.6 Add `test_year_range_inclusive_both_ends`: same seed, call with `year_start=2023, year_end=2024`, assert 2023 + 2024 episodes returned (2025 excluded).
- [x] 2.7 Add `test_n_total_matched_reports_full_count`: seed 8 episodes all matching filters, call with `n=3`, assert `n_returned=3` and `n_total_matched=8`.
- [x] 2.8 Add `test_n_validation_rejects_above_20`: assert Pydantic `ListEpisodesInput(n=25)` raises ValidationError; assert `n=0` also rejected.
- [x] 2.9 Add `test_year_start_after_year_end_rejected`: assert `ListEpisodesInput(show_id=<id>, year_start=2025, year_end=2024)` raises ValidationError.
- [x] 2.10 Run `cd backend && pytest tests/test_list_episodes_recency.py -v` and confirm all 8 tests pass (exit 0).

## 3. Add `find_episodes_by_date_range` sort/limit kwargs

- [x] 3.1 In `backend/app/services/episode_finders.py`, update `find_episodes_by_date_range` signature to accept `order: Literal['newest', 'oldest'] = 'newest'` and `limit: int | None = None` keyword-only.
- [x] 3.2 Modify the function's SQL template to interpolate the order direction (DESC for 'newest', ASC for 'oldest') and conditionally append `LIMIT :limit` only when `limit is not None`. Defensive: assert `limit is None or limit >= 1` at function entry, raise ValueError otherwise.
- [x] 3.3 Add test `test_date_range_with_limit_caps_results` in `backend/tests/test_list_episodes_recency.py`: seed 5 episodes within range, call `find_episodes_by_date_range(db, show_id, start, end, limit=2)`, assert 2 results returned in DESC order.
- [x] 3.4 Add test `test_date_range_order_oldest_reverses_sort`: same seed, call with `order='oldest', limit=2`, assert ASC order.
- [x] 3.5 Add test `test_date_range_backwards_compat_no_kwargs`: call `find_episodes_by_date_range(db, show_id, start, end)` (no new kwargs), assert default behaviour (DESC + unbounded) is preserved.
- [x] 3.6 Re-run `cd backend && pytest tests/test_list_episodes_recency.py -v` and confirm new tests pass. Also run `pytest tests/test_query_chat_metadata_filter.py` (existing test that uses `find_episodes_by_date_range`) to confirm rule-based caller still works.

## 4. Update SYSTEM_PROMPT with grounding rules + tool routing hint

- [x] 4.1 Read `backend/app/services/chat_agent/prompts.py` end-to-end to map current section order (role / tool-eager / grounded-refusal / tool list).
- [x] 4.2 Insert new section "事實 grounding 規則" between the grounded-refusal section and the tool list. Content SHALL match the spec verbatim: 6 numbered fabrication-forbidden categories + insufficient-info disclaimer rule + inference-content disclaimer rule.
- [x] 4.3 Append a tool routing hint to the same section: "需要 sort 或限定數量 → list_episodes 或 find_episodes_by_date_range 帶 limit；需要列出全部符合條件的集數 → 用既有 find_episodes_by_* 系列無 limit。"
- [x] 4.4 Add the tool entry for `list_episodes` in the tool list block within SYSTEM_PROMPT (one-line description matching the ToolSpec description from task 1.5).
- [x] 4.5 Create `backend/tests/test_chat_agent_grounding_prompt.py` with one snapshot-style test: load `SYSTEM_PROMPT`, assert each of the 6 categories appears verbatim, assert the inference disclaimer phrase "請以節目實際內容為準" appears, and assert the routing hint mentioning `list_episodes` appears. Run `cd backend && pytest tests/test_chat_agent_grounding_prompt.py -v` and confirm pass.

## 5. Prod chrome-devtools verification — recency tool (A)

- [ ] 5.1 Commit + push tasks 1-4 to main (gitleaks scan first per `feedback_public_repo_commit_safety.md`). Trigger backend redeploy via Zeabur CLI (backend service id `69eb10360da29f05f49a4b0b`).
- [ ] 5.2 After deploy reaches RUNNING and curl `/me` returns 200 with admin role, open chrome-devtools-mcp and navigate to https://app.podcastrag.app/. Switch to 對話 tab on 曼報 show.
- [ ] 5.3 Run scenario S-A1 — recency query "最新一集的來賓是誰？": send the chat request with `?debug_trace=true`. Assert `tool_calls` array contains at least one entry where `name == "list_episodes"`. Assert `tool_calls[*].args` includes the current show_id and an `n` value between 1 and 5. Assert the final answer references an actual episode title returned by the tool call (cross-check via `/episodes/{id}` API). Save screenshot + trace JSON to `/tmp/ordinal_evidence/`.
- [ ] 5.4 Run scenario S-A2 — "最舊五集的標題是什麼？": same protocol; assert `list_episodes` call with `order='oldest'` and `n` between 1 and 5; answer lists 5 actual episode titles in ascending date order.
- [ ] 5.5 Run scenario S-A3 — "2024 年最後一集講什麼歌單？": assert `list_episodes` call with `topic='歌單'` and `year_start=2024, year_end=2024` and `order='newest', n=1`; answer references a real 2024 episode whose description chunks contain "歌單" (cross-check via DB).
- [ ] 5.6 Run scenario S-A4 — "上週最舊一集是哪集？": assert agent computes a 7-day datetime range (start ≈ `<now> - 7 days`) and calls `find_episodes_by_date_range(..., order='oldest', limit=1)`. Acceptable: agent may pick a slightly different relative window (e.g., last 14 days) if no episodes in last 7; the key behaviour is the use of `limit=1` + `order='oldest'`.

## 6. Prod chrome-devtools verification — multi-turn ordinal carry (B, verify-only)

- [ ] 6.1 In the same chrome-devtools session as task 5, use the existing logged-in admin session. Pick show 曼報 (show_id=88702ed8-6fa0-49ec-bae4-34ac7c6d631c). Send turn 1 chat request: "歌單有哪幾集？" with `?debug_trace=true`. Save the response.
- [ ] 6.2 Inspect turn 1 trace: assert at least one tool call where `name in ('find_episodes_by_topic', 'list_episodes')` with `topic` argument matching '歌單'. Record the returned episode IDs (the list that should populate `last_enumeration_episodes`).
- [ ] 6.3 In the same session (same `session_id` cookie), send turn 2: "第三集是什麼內容？". Inspect trace. Assert the first tool call is `get_episode_summary` with `episode_id` equal to the third UUID from the turn 1 enumeration list (`last_enumeration_episodes[2]`). Pass if true.
- [ ] 6.4 Repeat tasks 6.1-6.3 for show 壹加壹電台 and 這又沒有很屌 (fetch show_ids from chrome-devtools `/shows` API call earlier). Track pass / fail per show.
- [ ] 6.5 Aggregate results: if at least 2 of 3 shows pass turn 2 with index-correct `get_episode_summary` call, mark multi-turn ordinal carry as VERIFIED in case study. If fewer than 2 pass, write a follow-up section in case study with: per-show failure mode, suspected root cause (prompt wording / state not written / TTL expired), and draft for a sub-change `multi-turn-ordinal-carry-fix` to add to `project_pending_followups.md`.

## 7. Prod chrome-devtools verification — hallucination grounding (C)

- [ ] 7.1 Run S-C1 (cross-show fabrication): on 這又沒有很屌, ask "迪拉胖在哪個節目訪問過 X 嘉賓?" (a guest who never appeared); inspect answer — SHALL NOT mention any other show name not in tool results, SHALL include "資料不足" or equivalent.
- [ ] 7.2 Run S-C2 (verbatim quote fabrication): on 曼報, ask "Manny 怎麼評論 AI 泡沫的具體一句話？"; inspect answer — SHALL NOT contain text in 「」 attributed to Manny unless that exact text is in tool result chunks (search the answer's quoted text in tool_calls[*].result_full).
- [ ] 7.3 Run S-C3 (statistical fabrication): ask "馬世芳一共上過幾集？"; inspect answer — if count appears, cross-check via `find_episodes_by_guest(guest='馬世芳')` tool call result; SHALL be exact match.
- [ ] 7.4 Run S-C4 (inference disclaimer): ask "這個節目整體風格偏向哪種？"; inspect answer — SHALL include the disclaimer phrase "請以節目實際內容為準" (or equivalent) at the end.

## 8. LLM judge eval rerun

- [ ] 8.1 Refresh admin E2E backdoor session per `reference_e2e_backdoor.md` (save session to `/tmp/session_id` chmod 600).
- [ ] 8.2 Run `nohup python3 -u backend/scripts/run_chat_agent_eval.py --dataset backend/eval/datasets/extended-multi-turn-40.json --backend-url https://podcastrag-api.zeabur.app --auth-token <SESSION> --top-k 5 --label grounding-and-ordinal-2026-05-XX --origin https://app.podcastrag.app --out backend/eval/results/chat_eval_grounding_and_ordinal.json > /tmp/eval_grounding.log 2>&1 &`. Disown. Per `feedback_background_task_lifecycle.md` use nohup + persistent log; do not rely on shell session.
- [ ] 8.3 After eval finishes (wait ~30 min, monitor via `wc -l /tmp/eval_grounding.log` going past ~200 lines), parse `backend/eval/results/chat_eval_grounding_and_ordinal.json`. Compute `aggregate.answer_quality_severe_rate` from per-turn LLM judge `severity` field (count `severe` / total).
- [ ] 8.4 Compare to baseline 0.20 (from `enable-agentic-chat-default-on` archive). Pass criteria: severe rate ≤ 0.10 AND `recall_at_k_mean >= 0.40` (not worse than baseline) AND `answer_match_mean >= 0.55`.
- [ ] 8.5 If pass: mark eval gate PASSED in case study. If fail (severe rate > 0.10 OR regression in other metrics): write a detailed failure analysis section in case study listing the top 5 worst-scoring questions + suspected prompt rule needing tuning + draft a follow-up sub-change `agentic-grounding-prompt-tune-v2`. Do NOT block archive on this — archive with the rerun result captured.

## 9. Case study + release log + archive

- [ ] 9.1 Create `docs/case-studies/agentic-prompt-grounding-and-ordinal-tool-2026-05-XX.md` (date = ship date). Sections: "Recency tool prod evidence (S-A1..S-A4 trace + answer snippets)", "Multi-turn ordinal carry verify result (per-show pass / fail)", "Hallucination prevention scenarios (S-C1..S-C4 outputs)", "LLM judge severe rate before / after (numbers + per-question delta)".
- [ ] 9.2 Draft a release log entry for `src/releaseLog.jsx` using `feedback_release_log_style.md` (user-facing language, no technical jargon): tag=fix, milestone=v1.8, title 「對話模式找最新 / 最舊集數變聰明 + 答案更老實」(zh) / "Chat Mode Recency Lookup + Honest Answers" (en). Bullets: (1) 問「最新三集」「2024 年最後一集歌單」這類問題現在會直接答, (2) 對話多輪對「第三集是什麼」這類序數提問會正確跳前一輪列舉的第三項, (3) 答案不會再亂編節目名 / 來賓 / 集數 / 統計數字, (4) 推論性質的答案會主動標註「請以節目實際內容為準」. Wait for user confirmation before committing.
- [ ] 9.3 After user approves release log draft, commit it + bump `index.html` cache-bust for `src/releaseLog.jsx` (current v=7 → v=8). Push.
- [ ] 9.4 Trigger frontend redeploy via Zeabur CLI (frontend service id `69eb27320da29f05f49a5260`). Verify deploy by curling `https://app.podcastrag.app/index.html` for the new `?v=8` substring.
- [ ] 9.5 Run `/spectra-archive agentic-prompt-grounding-and-ordinal-tool` only after tasks 5-8 evidence is fully captured AND user approves the release log entry.
