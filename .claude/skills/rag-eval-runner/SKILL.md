---
name: rag-eval-runner
description: "Run a RAG eval baseline against a backend, or extend the golden set"
license: MIT
metadata:
  version: "1.0"
---

Operate the PodcastRAG eval framework: run a baseline, build/audit a golden set, or rebake the judge.

## When to invoke

- User asks to "跑 eval"、"run RAG eval"、"check Recall@K"、"eval baseline"
- User wants to add a new podcast show's golden set
- User says "judge mismatched my call" / "rebake the judge"

## Layout (read this first)

```
backend/eval/
  judge_config.py          # PRODUCTION_JUDGE_MODEL — currently gpt-5-nano (calibration debt → R1.3)
  metrics/
    recall.py              # recall_at_k(top, gt, k=5)
    mrr.py                 # mrr(retrieved_per_q, gt_per_q) + reciprocal_rank
    judge_metrics.py       # judge_score(question, answer, context) — DeepEval GEval wrapper
  runners/
    run.py                 # main eval runner (CLI)
  scripts/
    build_golden_set.py    # LLM synthesis + validation (CLI)
    judge_bakeoff.py       # judge candidate Spearman bake-off (CLI)
  datasets/
    _schema.json           # JSON-schema for golden-set dataset
    this-not-that-cool.json   # first show, v2 (10 sentinel + 38 audited core = 48)
  results/                 # gitignored output dir
```

## Recipe 1 — Run an eval baseline

```bash
# From repo root.
# Step 1: exchange e2e HMAC token for a 15-min session cookie. The file at
# ~/.config/podcastrag/e2e-token is the HMAC pre-shared secret, NOT a session
# token — passing it directly to the runner triggers anonymous IP rate-limit
# (20/day) and you'll see HTTP 429 on every search call.
HMAC=$(cat ~/.config/podcastrag/e2e-token)
SESSION=$(curl -sS -i "https://api.podcastrag.app/auth/_e2e_login?token=$HMAC" \
  | grep -i "set-cookie: session_id" | head -1 | sed -E 's/.*session_id=([^;]+).*/\1/')

export EVAL_AUTH_TOKEN="$SESSION"
export OPENAI_API_KEY=<aihub_key>  # for judge (if --skip-judge omitted)

# Step 2: run.
python -m backend.eval.runners.run \
  --dataset backend/eval/datasets/this-not-that-cool.json \
  --backend-url https://api.podcastrag.app \
  --top-k 5 \
  --out-dir backend/eval/results
```

- Add `--skip-judge` for retrieval-only (Recall@K + MRR + latency) — no AIHUB cost, no `/query` quota decrement.
- Session TTL is 15 min; if your run takes longer (e.g. judge enabled, ~5s per item), re-exchange before starting.
- Output: `eval-{slug}-{timestamp}.json` + `.md` in `--out-dir`.
- Negative items (`ground_truth_chunk_ids: []`) are excluded from Recall/MRR averages but still scored by the judge.

## Recipe 2 — Build a golden set for a new show

```bash
export OPENAI_API_KEY=<aihub_key>

# 1. Hand-craft the 10-item sentinel set first (use existing dataset as template).
#    Sentinel items: human-verified ground-truth chunk_ids, sentinel=true.
#    Distribution: fact 3 / comprehension 2 / cross-episode 2 / negative 2 / code-switch 1.
#    Anchor each item to specific timestamps via /episodes/{id}/transcript.

# 2. Synthesize ~40 core items (LLM gpt-4o + sentinel few-shot).
python -m backend.eval.scripts.build_golden_set \
  --show-id <uuid> \
  --show-slug <lowercase-slug> \
  --backend-url https://api.podcastrag.app \
  --sentinel-path backend/eval/datasets/<slug>.json \
  --n-core 40 \
  --out /tmp/core-draft.json

# 3. Audit. Triage three buckets: keep / minor-edit / drop. Re-run for the
#    drop-bucket using --quota '{"fact":N,...}' and --ban-topics '["X","Y"]'
#    to avoid duplicate themes.

# 4. Predict-check negatives. For each candidate negative question, hit the
#    public search API and confirm RAG doesn't accidentally find a match:
curl -X POST https://api.podcastrag.app/shows/<id>/search \
  -H 'Content-Type: application/json' -d '{"question":"<q>","k":3}'

# 5. Merge sentinel + audited core into a single dataset JSON, validate
#    against backend/eval/datasets/_schema.json.
```

## Recipe 3 — Rebake the judge

The judge model is locked in `judge_config.py`. To swap it:

```bash
export OPENAI_API_KEY=<aihub_key>
python -m backend.eval.scripts.judge_bakeoff --write-config
```

This evaluates 4 candidates (gpt-5-nano / gemini-2.5-flash-lite / gpt-4o-mini / claude-haiku-4-5) against the 40-item judge mini-set, scores Spearman correlation against human scores, and writes the cheapest passing candidate (Spearman ≥ 0.7) to `judge_config.py`. Without `--write-config` it prints the table only.

⚠️ Calibration debt: as of 2026-05-07 no candidate passed 0.7 — `gpt-5-nano` is locked as a placeholder (Spearman 0.414, $0.012 / 40 items). The mini-set was built with an "all-knowing reader" perspective; rebuild it from a "judge-only-sees-retrieved-context" perspective and rebake. See `docs/research/r1-judge-bakeoff-2026-05-07.md`.

## Common pitfalls

- **Background tasks must use `nohup` + tee to a real file** (per `feedback_background_task_lifecycle.md` memory). `run_in_background` alone dies with the session.
- **gpt-4o through Zeabur AI Hub wraps JSON in ```json fences** even when `response_format=json_object` is set. `build_golden_set.py` already strips them — if you write a new LLM call, do the same.
- **Search API rate limit**: anonymous callers get 20/day per IP. Always pass `--auth-token` for eval runs (any logged-in user works; e2e-login token is fine).
- **Cross-episode items must anchor ≥2 distinct episode_ids** — the validator already checks this; don't accept hand-written items that violate it.
- **Negative items: predict-check via prod search BEFORE finalising**. A "false negative" (RAG accidentally finds an answer) blows up your judge score on that item.

## Validation

After any dataset edit, run:

```bash
cd backend && python -m pytest tests/test_eval_*.py tests/test_golden_set_dataset.py -v
```

The `test_v2_dataset_has_correct_distribution` test pins the histogram — adjust `EXPECTED_TYPE_HISTOGRAM_V2` and `EXPECTED_TOTAL_V2` if you intentionally change the dataset shape.
