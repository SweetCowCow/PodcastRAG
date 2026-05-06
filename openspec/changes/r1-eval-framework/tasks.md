# Implementation Tasks

## Stage A — Judge bake-off + Golden set v1 (session 1)

### A.1 Judge bake-off

- [x] 1.1 Implements requirement `Judge bake-off runs 4 candidates against a hand-scored mini-set` (mini-set creation). Hand-craft 20 mini-set items at `backend/eval/datasets/_judge_minisset.json`. (2026-05-06 擴增至 40 題；分布 5×10 / 4×7 / 3×4 / 2×5 / 1×14，第 31-40 題為 cross-episode aggregation，貢獻大量 score=1 樣本給 Spearman headroom)
- [x] 1.2 Implements requirement `Judge bake-off runs 4 candidates against a hand-scored mini-set` (script). Write `backend/eval/scripts/judge_bakeoff.py`: load mini-set; for each candidate model in `[gpt-5-nano, gemini-2.5-flash-lite, gpt-4o-mini, claude-haiku-4-5]` call DeepEval `FaithfulnessMetric` configured against Zeabur AI Hub base URL with that model; collect normalized scores; compute Spearman vs `human_score`; estimate cost per run from token counts × Hub pricing constants (hard-code 2026-05-05 prices). Print result table sorted by Spearman desc.
- [x] 1.3 Implements requirement `Production judge is selected by Spearman threshold and cost`. Extend `judge_bakeoff.py` with `--write-config` flag: select first row passing Spearman ≥ 0.7 AND lowest `cost_usd`; write `PRODUCTION_JUDGE_MODEL = "<id>"` and `JUDGE_PROVIDER_BASE_URL = "https://hnd1.aihub.zeabur.ai/v1"` to `backend/eval/judge_config.py`. If zero pass threshold: print failure message and exit 1, do not modify config.
- [x] 1.4 跑 bake-off 三輪（Faithfulness 兩次、GEval 一次），最終手動鎖 `gpt-5-nano`（Spearman 0.414，bypass 0.7 threshold）。Spearman + cost 表記在 `docs/research/r1-judge-bakeoff-2026-05-07.md`（不入 commit）。Calibration debt → R1.3。同步 fix 了 3 個 bug：py3.11 spearman、raw scores 落盤、Faithfulness → GEval pivot。Script 與 judge_config 已更新。

### A.2 Golden set v1 (這又沒有很屌)

- [x] 2.1 Implements requirement `Golden set is stored per-show as JSON under backend/eval/datasets`. Write `backend/eval/datasets/_schema.json` (JSON Schema draft-7) declaring required top-level fields `show_slug`, `show_id`, `version`, `created_at`, `items[]`. Validate with `jsonschema` package (add to backend dev requirements).
- [x] 2.2 Implements requirements `Each golden set item has type, ground-truth chunks, and sentinel flag` and `Initial golden set covers 50 items across 5 types`. Write `backend/eval/scripts/build_golden_set.py` helper: takes show_id + N (default 50), samples 5 episodes' transcript chunks, calls LLM (Hub gpt-4o) with few-shot prompt to generate questions per type-quota; LLM is prompted to also propose `ground_truth_chunk_ids` (it sees chunk_id list with each candidate chunk).
- [ ] 2.3 Hand-craft 10 sentinel items for「這又沒有很屌」(distribution: fact 3, comprehension 2, cross-episode 2, negative 2, code-switch 1). For each: write the question, expected_answer_keywords, and verify ground_truth_chunk_ids by manually playing the transcript at the marked time. Add to dataset JSON with `sentinel: true`.
- [ ] 2.4 Run `build_golden_set.py` to synthesise 40 core items targeting the type quota (fact 16, comprehension 10, cross-episode 8, negative 4, code-switch 2). Output to a draft file.
- [ ] 2.5 Sample-audit ~30% of synthetic core items (12 items, evenly across types). Fix items where the question is malformed, the proposed ground_truth_chunk_ids are wrong, or expected_answer_keywords are too generic. Reject and regenerate items that cannot be salvaged.
- [ ] 2.6 Merge sentinel + audited core into final `backend/eval/datasets/this-not-that-cool.json`. Validate against `_schema.json` AND verify the type histogram matches `{fact: 19, comprehension: 12, cross-episode: 10, negative: 6, code-switch: 3}` AND sentinel count is exactly 10.
- [x] 2.7 Add `backend/tests/test_golden_set_dataset.py` with a single test that loads `this-not-that-cool.json`, validates against `_schema.json`, asserts type histogram, and asserts 10 sentinel items. Confirms the dataset stays correct on future edits.

## Stage B — Eval framework + CI + skill + reminder (session 2)

### B.1 Metrics + runner

- [x] 3.1 Implements requirement `Recall@K and MRR are computed per query against ground-truth chunks` (recall). Write `backend/eval/metrics/recall.py` with `recall_at_k(top_chunks: list[str], ground_truth: list[str], k: int = 5) -> float | None` returning None for empty ground_truth (caller filters), else `len(set(top_chunks[:k]) & set(ground_truth)) / len(ground_truth)`. Pure stdlib, no numpy.
- [x] 3.2 Implements requirement `Recall@K and MRR are computed per query against ground-truth chunks` (mrr). Write `backend/eval/metrics/mrr.py` with `mrr(top_chunks: list[str], ground_truth: list[str]) -> float` returning `1/(rank+1)` for first hit (1-based), else 0.
- [x] 3.3 Add `backend/tests/test_eval_metrics.py` with parameterized tests covering each example table row in the spec scenarios for Recall@5 and MRR (including the 3-item table, the 0.5 MRR case, and the negative-item-excluded case).
- [x] 3.4 Add `deepeval` to `backend/requirements.txt` (pinned version, latest stable as of 2026-05-05). Verify `pip install -r requirements.txt` succeeds and `from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric` works.
- [ ] 3.5 Implements requirement `Faithfulness and Answer Relevancy are scored via DeepEval with a configured judge`. Write `backend/eval/runners/judge_metrics.py` thin wrapper: configures DeepEval to point at `JUDGE_PROVIDER_BASE_URL` from `judge_config.py` using `OPENAI_API_KEY` env (hub uses OpenAI-compatible auth); exposes `score_faithfulness(answer, contexts) -> float` and `score_answer_relevancy(question, answer) -> float`.
- [ ] 3.6 Implements requirement `eval/run.py orchestrates one full eval run end-to-end`. Write `backend/eval/run.py` CLI with argparse for `--dataset`, `--backend-url`, `--auth-token` (env fallback `EVAL_AUTH_TOKEN`), `--top-k` (default 5), `--out`. Loop items: POST `/shows/{show_id}/query`, derive `top_chunks` from `citations` (use `f"ep:{c.episode_id}@{c.start_time:.2f}"`), score recall + mrr + faithfulness + answer_relevancy, build per-item rows, aggregate overall + per_show, write JSON.
- [ ] 3.7 Add `backend/tests/test_eval_runner.py`: monkeypatch the backend HTTP call with a fixture returning canned `(answer, citations)`, run a 3-item synthetic dataset through `run.py` via subprocess or function call, assert the output JSON has the required top-level keys (`dataset`, `run_started_at`, `run_finished_at`, `items`, `aggregates`) and that `aggregates.overall.recall_at_5` matches the expected value computed from the canned data.

### B.2 CI workflow

- [ ] 4.1 Implements requirement `CI runs eval nightly on main and uploads JSON as an artifact`. Write `.github/workflows/eval.yml` triggered on `schedule: cron '0 3 * * *'` and `workflow_dispatch` (no `pull_request` trigger). Add explicit `if: github.ref == 'refs/heads/main'` guard at the job level so PR-via-dispatch can't run.
- [ ] 4.2 Workflow steps: checkout; setup Postgres + Redis service containers (sidecar); install backend deps; run alembic migrations; seed minimal data (insert one show row for「這又沒有很屌」+ one episode + run a small embedding pass) — OR — pull a snapshot fixture; start backend with uvicorn; wait for `/healthz`; mint an admin session via `/auth/_e2e_login` env-gated route; run `python backend/eval/run.py --dataset this-not-that-cool --auth-token $TOKEN`; upload `backend/eval/results/*.json` as artifact named `eval-results-${{ github.run_id }}`. Use `continue-on-error: true` on the eval step so the artifact upload always runs.
- [ ] 4.3 Manually trigger `workflow_dispatch` once after merge; verify the artifact appears in Actions UI with the expected JSON inside.

### B.3 Golden Set Builder skill

- [ ] 5.1 Write `.claude/skills/golden-set-builder/SKILL.md` describing the skill's invocation surface (input args: show_id, n=50, mode={v1|incremental}; output: dataset JSON), behavior (sample chunks → LLM synthesise → LLM ground-truth label → human audit prompts → write JSON), and explicit triggering hints ("when user says 'build golden set for show X' or 'add golden set' or '建立 X 節目的 golden set'").
- [ ] 5.2 Inside SKILL.md write the step-by-step workflow Claude follows: (1) call backend API to enumerate episodes + chunks; (2) sample 5 episodes weighted toward longest transcripts; (3) call `backend/eval/scripts/build_golden_set.py` with type quotas; (4) for sentinel items, prompt user to type 10 questions one by one with timestamp anchors; (5) for core items, present 12 randomly-selected synthetic items (evenly across types) for user yes/no/edit; (6) merge and write final JSON; (7) auto-run `test_golden_set_dataset.py`-style validation before declaring done.
- [ ] 5.3 Write `.claude/skills/golden-set-builder/README.md` (separate from SKILL.md, used by humans) explaining: prerequisite (backend running with show indexed), expected time (~1 hour first time, ~30 min incremental), output location, how the file plugs into the eval framework, and an example `/build-golden-set <show_id>` invocation.
- [ ] 5.4 Self-test the skill end-to-end by writing a 30-item dataset for a fictional 2nd show fixture (NOT「這又沒有很屌」— don't double-build that one); confirm output validates against `_schema.json`; then delete the fixture file. This is a smoke test of the skill, not a deliverable.

### B.4 Maintenance reminder

- [ ] 6.1 Implements requirement `Admin endpoint surfaces golden-set freshness per show`. Add `backend/app/schemas/golden_set_status.py` with `GoldenSetStatusEntry` Pydantic model matching the spec fields (show_id, show_title, show_slug, dataset_exists, item_count, last_updated, episodes_added_since, needs_refresh). Add `backend/app/api/admin/golden_set_status.py` exposing `GET /admin/golden-set-status` requiring admin: list shows from DB, for each compute slug (consistent with dataset filename), check if `backend/eval/datasets/{slug}.json` exists in the deployed image, read item count + created_at, query episodes count where `episodes.created_at > dataset_last_updated`, compute needs_refresh flag, return list. Wire into `backend/app/api/admin/__init__.py`.
- [ ] 6.2 Implements requirement `Monthly Celery beat task emails admin when datasets need refresh`. Add `backend/app/workers/golden_set_reminder.py` with a Celery task that mirrors the admin endpoint logic, builds a Chinese email body listing only shows where `needs_refresh: true` (with show_title + episodes_added_since + last_updated), calls `zsend.send_email(...)` if at least one show needs refresh AND `ZSEND_API_KEY` is set; otherwise log clean. Use a Redis key `golden_set_reminder:last_sent:{YYYY-MM-DD}` with 25-hour TTL to dedupe same-day re-runs. Register in `backend/app/workers/celery_app.py` `beat_schedule` with `crontab(day_of_month=1, hour=3, minute=0)`.
- [ ] 6.3 Add `backend/tests/test_golden_set_reminder.py` covering the four spec scenarios: (a) two need-refresh shows produce one email mentioning both; (b) all-fresh case logs and does not send; (c) same-day re-run is deduped; (d) missing `ZSEND_API_KEY` logs warning and exits clean. Use mock for `zsend.send_email` and a fake Redis (fakeredis or monkeypatch).

## Stage C — Verify & Ship

- [ ] 7.1 Run full backend test suite (`pytest backend/`) and confirm zero regressions plus all new tests pass (test_golden_set_dataset, test_eval_metrics, test_eval_runner, test_golden_set_reminder).
- [ ] 7.2 Manually run `python backend/eval/run.py --dataset this-not-that-cool` against dev backend (admin session via `_e2e_login`); confirm JSON file lands in `backend/eval/results/`, aggregates contain all 4 metrics, and per-show + overall both populated. Record the first numbers in `docs/research/r1-baseline-2026-05-05.md` (per memory rule, NOT committed) so future R3/R2/R4 changes have a real baseline to compare.
- [ ] 7.3 Commit and push. Verify Zeabur backend redeploys with new admin endpoint (use `service redeploy` fallback if webhook stalls per `feedback_zeabur_webhook_unreliable.md`). Use chrome-devtools-mcp on prod to: (a) hit `/admin/golden-set-status` as admin and confirm the dataset entry appears with correct `needs_refresh: false`; (b) trigger the GitHub Actions workflow `eval.yml` via workflow_dispatch on main and confirm the artifact appears.

## Design Decision Coverage

Tasks above implement these design decisions:
- `Judge model 用 Spearman 相關係數選` → 1.2, 1.3
- `Bake-off 候選池` → 1.2
- `Golden set 結構：JSON 檔，per show 一檔` → 2.1, 2.6
- `Recall@5 與 MRR 計算` → 3.1, 3.2, 3.3
- `Eval runner 直接打本地 backend` → 3.6
- `CI 策略：nightly only on main` → 4.1, 4.2
- `Skill 半自動流程` → 5.1, 5.2, 5.4
- `路線 B 提醒：用 Celery beat` → 6.2
