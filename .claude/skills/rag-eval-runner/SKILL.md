---
name: rag-eval-runner
description: "Run a RAG eval baseline against a backend, or extend the golden set. Enforces test-driven canary + metric-sanity + preflight + checkpointing + persistent runner."
license: MIT
metadata:
  version: "2.0"
---

Operate the PodcastRAG eval framework: run a baseline, build/audit a golden set, or rebake the judge.

## When to invoke

- User asks to "跑 eval"、"run RAG eval"、"check Recall@K"、"eval baseline"
- User wants to add a new podcast show's golden set
- User says "judge mismatched my call" / "rebake the judge"

## ⚠️ MANDATORY discipline gates (跑任何 full eval 前必須走完)

> 這些 phase 是 v2.0 加的，從 2026-05-10 R2.1 archive 卡關事件學到：今天 single-shot judge run 0.71 → 0.51 我們以為是 prompt regression，後來才發現 (a) judge variance 沒測 (b) answer 文字沒持久化導致根因都是結構推論。**沒走完這些 gate 不准跑 full eval。**

### Phase 0: Environment preflight（最多 30 sec）

跑前先 assert 環境正確 — 抓 `statistics.correlation` 3.12-only 那類 bug 在 0 樣本就掛掉而不是 38 min 之後。

```bash
#!/bin/bash
echo "== Phase 0: preflight =="

# Python version (some metrics need 3.12+)
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  python: $PYVER"
[ "$PYVER" \< "3.10" ] && { echo "  ❌ need 3.10+"; exit 1; }

# Required env vars
[ -z "$OPENAI_API_KEY" ] && { echo "  ❌ OPENAI_API_KEY 未設"; exit 1; }
[ ! -f ~/.config/podcastrag/e2e-token ] && { echo "  ❌ e2e-token 缺檔"; exit 1; }

# Dataset exists + valid JSON
DATASET="${1:-backend/eval/datasets/this-not-that-cool.json}"
python3 -c "import json; json.load(open('$DATASET'))" || { echo "  ❌ dataset invalid"; exit 1; }
ITEMS=$(python3 -c "import json; print(len(json.load(open('$DATASET'))['items']))")
echo "  dataset: $DATASET ($ITEMS items)"

# Backend reachable
curl -sS -m 5 -o /dev/null -w "  backend %{http_code}\n" https://api.podcastrag.app/stats

# Required Python packages exist (deepeval / openai)
python3 -c "import deepeval, openai" 2>&1 | head -1 || { echo "  ❌ missing deepeval/openai"; exit 1; }

echo "  ✓ preflight passed"
```

### Phase 1: Canary（3 樣本，dump 完整 I/O 給 user 看）

跑前挑 3 題（fact 1 + comprehension 1 + negative 1），用 patched runner 持久化 answer + retrieval_context，dump 給 user 確認 inputs / outputs / scores 合理才放大。

```bash
echo "== Phase 1: canary on 3 items =="
# 用 --canary 3 跑前 3 題（runner 必須支援 --canary N，沒有先 patch）
# 必須有 --persist-answers flag — 否則只有 score，事後沒辦法做 evidence-based prompt fix
python3 -m backend.eval.runners.run \
  --dataset "$DATASET" \
  --backend-url https://api.podcastrag.app \
  --auth-token "$SESSION" \
  --top-k 5 \
  --canary 3 \
  --persist-answers \
  --out-dir /tmp/canary-$(date +%s)
```

Dump 的內容必須包含 per-item：
- question
- retrieved chunk_ids (top 5)
- LLM answer 全文（不能 strip）
- judge_score + judge 原始 reasoning（GEval `evaluation_steps`）

**讓 user 確認 3 題都合理才繼續**。發現 anything weird（譬如 LLM 答案重複 / judge 給離譜分數）→ 停下來修，不要 full run。

### Phase 2: Metric sanity gate（sub-agent 評估）

派 sub-agent (Sonnet 即可) 用以下 prompt 檢查 metric 對 research question 是否合適：

```
你是 metric reviewer。研究問題是「<user 的目的>」。我們選了 metric「<Faithfulness GEval 1-5>」。
請評估：
1. 這個 metric 真的衡量到 research question 嗎？
2. 如果改動是 prompt strengthen citation，但 metric 衡量「context 內 answer 的可信度」，兩者是否對齊？
3. 給「合適 / 部分對齊 / 不合適」+ 一句理由。

如果 sub-agent 回「不合適」或「部分對齊」→ 停下跟 user 確認 gate 是不是設錯（譬如 R2.1 改 UI source presentation，硬要過 Faithfulness gate 邏輯不通）。
```

### Phase 3: Variance baseline（measure judge SD before declaring deltas）

**single-shot run 不能當 evidence**。跑同 prompt 同 dataset N 次（N=3 起跳），算 Judge mean SD：

```bash
echo "== Phase 3: variance baseline (3 runs same config) =="
for i in 1 2 3; do
  python3 -m backend.eval.runners.run \
    --dataset "$DATASET" --backend-url https://api.podcastrag.app \
    --auth-token "$SESSION" --top-k 5 --metric-level episode \
    --out-dir backend/eval/results
  sleep 30  # 避免 burst
done

# 算 SD
python3 -c "
import json, glob, statistics
files = sorted(glob.glob('backend/eval/results/eval-*.json'))[-3:]
scores = [json.load(open(f))['aggregate']['overall']['judge_score_mean'] for f in files]
print(f'judge means: {scores}')
print(f'mean: {statistics.mean(scores):.4f}, SD: {statistics.stdev(scores):.4f}')
print(f'⚠️ if SD ≥ 0.07, single-shot deltas < 0.14 are noise')
"
```

**Rule of thumb**：若 SD = 0.07，需要 **≥ 2 SD 差異**（即 |delta| ≥ 0.14）才能 95% 信賴 prompt 改動真的有效。

### Phase 4: Checkpoint every N samples

Runner 必須每 N 樣本（建議 N=10）寫 partial result 到 disk，crash 後可 resume：

```bash
# Runner 必須支援 --checkpoint-every 10 跟 --resume <path>
# 沒這兩個 flag → 先 patch runner（半小時）才 full run
```

實作 hint：每 10 題寫 `<out-dir>/.checkpoint.json`（覆蓋）+ 結束時刪。`--resume` 從 checkpoint 接續。

### Phase 5: Persistent runner（不是 run_in_background）

`run_in_background` 跟 session 綁死，session 退就死。長跑 eval 必須 `nohup` + 落盤 log + PID file：

```bash
echo "== Phase 5: persistent launch =="
mkdir -p /tmp/eval-runs
TS=$(date +%Y%m%dT%H%M%S)
LOG=/tmp/eval-runs/$TS.log
PIDFILE=/tmp/eval-runs/$TS.pid

nohup python3 -u -m backend.eval.runners.run \
  --dataset "$DATASET" --backend-url https://api.podcastrag.app \
  --auth-token "$SESSION" --top-k 5 --metric-level episode \
  --checkpoint-every 10 \
  --out-dir backend/eval/results \
  > "$LOG" 2>&1 &
echo $! > "$PIDFILE"
echo "  PID=$(cat $PIDFILE), log=$LOG"

# 驗證 process 真活著
sleep 5
kill -0 $(cat "$PIDFILE") 2>/dev/null && echo "  ✓ alive" || { echo "  ❌ died immediately"; tail "$LOG"; exit 1; }
```

⚠️ `python3 -u` 強制 unbuffered，否則 nohup 把 stdout buffer 到死掉才 flush。

---

## 走完 5 phase 後的 full run gate

| Gate | 條件 |
|---|---|
| ✓ preflight passed | env 全綠 |
| ✓ canary 3 題 user 看過 OK | I/O 合理 + judge 不離譜 |
| ✓ metric sanity 對齊 | sub-agent 給 「合適」 |
| ✓ variance SD measured | 知道後續 delta 要多大才 significant |
| ✓ checkpoint enabled | crash 不丟 |
| ✓ persistent runner alive | session 退也活 |

**6 個全綠**才能宣告「跑完整 eval」。少一個 → 結果不可信。

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
