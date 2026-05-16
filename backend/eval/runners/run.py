"""Main RAG eval runner — query backend retrieval/answer APIs against a golden set.

For each item:
  1. POST /shows/{show_id}/search to get top-K chunks (Recall@K, MRR).
  2. Optionally POST /shows/{show_id}/query to get the LLM-generated answer
     (judge score). Skipped if --skip-judge or auth missing.
  3. Aggregate per-type + overall metrics.

Output: JSON report + markdown summary in --out-dir.

Usage:
    python -m backend.eval.runners.run \\
        --dataset backend/eval/datasets/this-not-that-cool.json \\
        --backend-url https://api.podcastrag.app \\
        --auth-token "$EVAL_AUTH_TOKEN" \\
        --top-k 5 \\
        --out-dir backend/eval/results

Notes:
  - --auth-token is the e2e-login session cookie value (memory: e2e-login-backdoor).
    Required because /shows/.../search is rate-limited 20/day for anon callers.
  - Scoring dispatches on each item's `eval_mode`:
      * chunk_id        → Recall@K against ground_truth_chunk_ids (legacy path;
                          empty ground_truth → None, excluded from chunk mean —
                          this is how negative items are kept out of the average
                          while still being scored by the judge for "not mentioned").
      * open_set_lenient → any-anchor-hit → recall 1.0, else 0.0 (still aggregates
                          in the chunk-based group alongside chunk_id items).
      * enumeration     → ignore chunk anchors; compute episode_set_recall against
                          expected_episode_ids; aggregated into its own group so
                          the metric is not mixed with chunk-based items.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable

try:
    # Invoked as `python -m backend.eval.runners.run` from repo root
    from backend.eval.metrics.mrr import reciprocal_rank
    from backend.eval.metrics.recall import episode_set_recall, recall_at_k
except ModuleNotFoundError:
    # Invoked under pytest with cwd=backend/
    from eval.metrics.mrr import reciprocal_rank
    from eval.metrics.recall import episode_set_recall, recall_at_k


# Lenient chunk match: production retrieval returns chunk-level start_times
# (multiple segments aggregated; high-precision floats), while the golden set
# anchors at segment-level (clean 2-decimal). Bucket both to a window so a
# retrieved chunk that *contains* an anchor segment counts as a hit.
DEFAULT_MATCH_WINDOW_S = 10.0


def _bucket(chunk_id: str, window_s: float) -> tuple[str, int]:
    """Convert `ep:<uuid>@<seconds>` to (uuid, floor(seconds/window))."""
    try:
        head, tail = chunk_id.split("@", 1)
        ep_id = head.removeprefix("ep:")
        return (ep_id, int(float(tail) // window_s))
    except (ValueError, IndexError):
        return ("", -1)


def _to_lenient_ids(chunk_ids: list[str], window_s: float) -> list[str]:
    """Re-encode each chunk_id as `ep:<uuid>@<bucket>` for set-equality match."""
    return [f"ep:{ep}@{bucket}" for ep, bucket in (_bucket(c, window_s) for c in chunk_ids) if ep]

REPO_ROOT = Path(__file__).resolve().parents[3]


# ────────────────────────────────────────────────────────────────────
# HTTP helpers
# ────────────────────────────────────────────────────────────────────

def _fetch_csrf(backend_url: str, token: str, timeout: float = 10.0) -> str:
    """Hit /me to retrieve the HMAC-derived CSRF token. CSRF middleware requires
    X-CSRF-Token == HMAC(SESSION_SECRET, session_id) — the cookie's csrf_token
    value is random and NOT what the backend validates against. The frontend
    reads the derived token from /me response body."""
    if not token:
        return ""
    req = urllib.request.Request(
        f"{backend_url}/me", headers={"Cookie": f"session_id={token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()).get("csrf_token", "") or ""
    except (urllib.error.URLError, json.JSONDecodeError):
        return ""


_CSRF_CACHE: dict[str, str] = {}


def _post(url: str, body: dict, token: str, timeout: float = 60.0) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Cookie"] = f"session_id={token}"
        # Backend requires Origin + X-CSRF-Token for state-changing requests.
        # Cache the derived CSRF per token so we hit /me only once per run.
        if token not in _CSRF_CACHE:
            backend_root = url.rsplit("/", url.count("/") - 2)[0] if "://" in url else ""
            # Derive backend_url from full url: scheme://host/...
            from urllib.parse import urlparse
            p = urlparse(url)
            backend_root = f"{p.scheme}://{p.netloc}"
            _CSRF_CACHE[token] = _fetch_csrf(backend_root, token)
        csrf = _CSRF_CACHE[token]
        if csrf:
            headers["Origin"] = "https://app.podcastrag.app"
            headers["X-CSRF-Token"] = csrf
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _to_chunk_id(hit: dict) -> str:
    return f"ep:{hit['episode_id']}@{float(hit['start_time']):.2f}"


def _retrieve(
    backend_url: str, show_id: str, question: str, k: int, token: str,
) -> tuple[list[str], list[str], float]:
    """Return (chunk_ids, chunk_texts, latency_ms). Empty lists on failure."""
    t0 = time.monotonic()
    try:
        resp = _post(
            f"{backend_url}/shows/{show_id}/search",
            {"question": question, "k": k},
            token,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[warn] retrieve failed: {exc}", file=sys.stderr)
        return [], [], 0.0
    latency_ms = (time.monotonic() - t0) * 1000
    hits = resp.get("results", [])
    return [_to_chunk_id(h) for h in hits], [h.get("text", "") for h in hits], latency_ms


# Per-token one-time warning when chat-CSRF is unavailable. Avoids spamming
# stderr per enumeration item when the auth token is unusable.
_CHAT_CSRF_WARNED: set[str] = set()


def _retrieve_chat_enumeration(
    backend_url: str, show_id: str, question: str, token: str,
) -> tuple[list[str], int | None]:
    """Call the chat endpoint and extract `enumeration_episodes` episode_ids.

    R3.3 + r3-3-chat-enum-grounding shipped a chat-only enumeration path that
    `episode_finders.find_episodes_by_topic` / guest / date populate into the
    `ChatResponse.enumeration_episodes` field. This helper pulls those
    episode_ids so the eval runner can union them with the search-side
    chunks when scoring `eval_mode: "enumeration"` items.

    Fail-open contract (per spec `Chat endpoint failures fail-open with empty
    episode set`):
      - Returns `([], None)` on any failure (HTTP 5xx, missing CSRF, network
        timeout, malformed JSON, no auth token). `None` total signals "chat
        scoring inconclusive" so the diagnostic field downstream is `None`,
        not 0.
      - Returns `([], 0)` when the chat call succeeded BUT the response has
        no `enumeration_episodes` (chat path did NOT classify this question
        as enumeration). Distinct from failure — total=0 means "we asked
        and the answer is zero", not "we couldn't ask".
      - Returns `(episode_ids, total)` on success. `total` mirrors
        `enumeration_total` if present, else `len(episode_ids)`.
    """
    if not token:
        return [], None

    # CSRF gate. _post caches /me results in _CSRF_CACHE for performance;
    # we piggyback on the same cache. If the CSRF can't be obtained, fail
    # open once per token with a single startup-style warning, then quietly
    # skip subsequent enumeration items so prior search-only behavior is
    # preserved without spamming stderr.
    if token not in _CSRF_CACHE:
        _CSRF_CACHE[token] = _fetch_csrf(backend_url, token)
    if not _CSRF_CACHE.get(token):
        if token not in _CHAT_CSRF_WARNED:
            print(
                "[warn] chat-enum scoring disabled — CSRF token unavailable "
                "via /me. Falling back to search-only enumeration recall "
                "for the rest of this run.",
                file=sys.stderr,
            )
            _CHAT_CSRF_WARNED.add(token)
        return [], None

    try:
        resp = _post(
            f"{backend_url}/shows/{show_id}/query",
            {"question": question, "mode": "chat", "messages": []},
            token,
            timeout=60.0,
        )
    except urllib.error.HTTPError as exc:
        print(
            f"[warn] chat-enum query HTTP {exc.code} for question={question!r}",
            file=sys.stderr,
        )
        return [], None
    except (
        urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError,
    ) as exc:
        print(
            f"[warn] chat-enum query failed for question={question!r}: {exc}",
            file=sys.stderr,
        )
        return [], None
    except Exception as exc:  # noqa: BLE001 — fail-open contract
        print(
            f"[warn] chat-enum query unexpected error for question={question!r}: {exc}",
            file=sys.stderr,
        )
        return [], None

    enum_eps = resp.get("enumeration_episodes")
    if enum_eps is None:
        # Chat path saw the question but did NOT classify it as enumeration.
        # Distinct from a failure path; surfaces a dataset/path mismatch.
        return [], 0

    episode_ids: list[str] = []
    for ep in enum_eps:
        if not isinstance(ep, dict):
            continue
        eid = ep.get("episode_id")
        if eid:
            episode_ids.append(str(eid))

    total = resp.get("enumeration_total")
    if not isinstance(total, int):
        total = len(episode_ids)
    return episode_ids, total


# R2.1-fix Fix 1.3: strip `[N]` / `[N,M,...]` ref tokens before sending the
# answer to the judge. The backend serves `[N]` brackets so the frontend can
# render source cards on hover, but LLM judges treat the brackets as noise
# and dock points (Pattern B in r21-prompt-regression case study).
_RUNNER_CITATION_RE = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")


def _strip_inline_citations(text: str) -> str:
    if not text:
        return ""
    return _RUNNER_CITATION_RE.sub("", text).strip()


def _query(
    backend_url: str, show_id: str, question: str, token: str,
) -> tuple[str, list[str]]:
    """Return (answer_text, retrieval_context_texts). Empty on failure.

    The returned `answer_text` has inline `[N]` citation tokens stripped so
    LLM judges see clean prose; the per-item `out_items["answer"]` written
    later in the run also stores this cleaned form for traceability.
    """
    try:
        resp = _post(
            f"{backend_url}/shows/{show_id}/query",
            {"question": question, "mode": "chat", "messages": []},
            token,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[warn] query failed: {exc}", file=sys.stderr)
        return "", []
    raw_answer = resp.get("answer") or resp.get("response") or ""
    sources = resp.get("sources") or resp.get("results") or []
    context = [s.get("text", "") for s in sources if s.get("text")]
    return _strip_inline_citations(raw_answer), context


# ────────────────────────────────────────────────────────────────────
# Aggregation
# ────────────────────────────────────────────────────────────────────

def _aggregate(items: list[dict]) -> dict:
    """Compute overall + per-type means, split between chunk-based and enumeration groups.

    - chunk_based group: items with eval_mode in {chunk_id, open_set_lenient}.
      Reports recall_at_k_mean / mrr (legacy semantics; empty-gt → None excluded).
    - enumeration group: items with eval_mode == enumeration.
      Reports episode_set_recall_mean instead; chunk-level Recall/MRR are N/A.

    Judge / latency are summarised across all items regardless of eval_mode.
    """
    def _chunk_agg(group: list[dict]) -> dict:
        recalls = [it["recall_at_k"] for it in group if it["recall_at_k"] is not None]
        rrs = [it["reciprocal_rank"] for it in group if it["recall_at_k"] is not None]
        judges = [it["judge_score"] for it in group if it.get("judge_score") is not None]
        latencies = [it["latency_ms"] for it in group if it.get("latency_ms")]
        return {
            "n": len(group),
            "n_scored_retrieval": len(recalls),
            "recall_at_k_mean": round(mean(recalls), 4) if recalls else None,
            "mrr": round(mean(rrs), 4) if rrs else None,
            "judge_score_mean": round(mean(judges), 4) if judges else None,
            "latency_p95_ms": round(_p95(latencies), 1) if latencies else None,
        }

    def _enum_agg(group: list[dict]) -> dict:
        ep_recalls = [it["episode_set_recall"] for it in group if it.get("episode_set_recall") is not None]
        judges = [it["judge_score"] for it in group if it.get("judge_score") is not None]
        latencies = [it["latency_ms"] for it in group if it.get("latency_ms")]
        return {
            "n": len(group),
            "n_scored_retrieval": len(ep_recalls),
            "episode_set_recall_mean": round(mean(ep_recalls), 4) if ep_recalls else None,
            "judge_score_mean": round(mean(judges), 4) if judges else None,
            "latency_p95_ms": round(_p95(latencies), 1) if latencies else None,
        }

    chunk_items = [it for it in items if it.get("eval_mode", "chunk_id") != "enumeration"]
    enum_items = [it for it in items if it.get("eval_mode") == "enumeration"]

    by_type: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_type[it["type"]].append(it)
    return {
        "chunk_based": _chunk_agg(chunk_items),
        "enumeration": _enum_agg(enum_items),
        "by_type": {t: _chunk_agg(g) for t, g in sorted(by_type.items())},
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(0.95 * (len(s) - 1))
    return s[idx]


# ────────────────────────────────────────────────────────────────────
# Markdown report
# ────────────────────────────────────────────────────────────────────

def _markdown_report(report: dict) -> str:
    m = report["metrics"]
    chunk = m.get("chunk_based", {})
    enum_grp = m.get("enumeration", {})
    level = report.get("metric_level", "chunk")
    k = report["top_k"]
    lines = [
        f"# RAG eval — {report['dataset']} ({report['version']})",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- backend: `{report['backend']}`",
        f"- judge_model: `{report.get('judge_model') or '(skipped)'}`",
        f"- top_k: {k}",
        f"- n_items: {report['n_items']}",
        "",
        "## Overall",
        "",
        "| metric | value |",
        "|---|---|",
        f"| Recall@{k} (chunk, {level}, n={chunk.get('n', 0)}) | {chunk.get('recall_at_k_mean')} |",
        f"| Episode Set Recall (enumeration, n={enum_grp.get('n', 0)}) | {enum_grp.get('episode_set_recall_mean')} |",
        f"| MRR (chunk group) | {chunk.get('mrr')} |",
        f"| Judge mean (1-5, all items) | {chunk.get('judge_score_mean')} |",
        f"| Latency P95 (ms, chunk group) | {chunk.get('latency_p95_ms')} |",
        "",
        "## By type",
        "",
        "| type | n | Recall@K | MRR | Judge | P95 ms |",
        "|---|---|---|---|---|---|",
    ]
    for t, agg in m["by_type"].items():
        lines.append(
            f"| {t} | {agg['n']} | {agg['recall_at_k_mean']} | {agg['mrr']} | "
            f"{agg['judge_score_mean']} | {agg['latency_p95_ms']} |"
        )
    return "\n".join(lines) + "\n"


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

def _to_episode_ids(chunk_ids: list[str]) -> list[str]:
    """Extract just the episode_id portion of `ep:<uuid>@<time>` strings."""
    out = []
    for cid in chunk_ids:
        head = cid.split("@", 1)[0]
        if head.startswith("ep:"):
            out.append(head[3:])
        elif head.startswith("desc:"):
            out.append(head[5:])
        else:
            out.append(head)
    return out


def _checkpoint_path(out_dir: Path) -> Path:
    return out_dir / ".checkpoint.json"


def _write_checkpoint_atomic(path: Path, payload: dict) -> None:
    """Write checkpoint via tmp + rename to avoid torn writes on crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_checkpoint(resume_path: Path, dataset_path: Path) -> tuple[list[dict], set[str]]:
    """Load checkpoint; verify dataset path matches the one recorded. Return (items, processed_ids)."""
    cp = json.loads(resume_path.read_text(encoding="utf-8"))
    recorded = cp.get("meta", {}).get("dataset", "")
    if recorded and recorded != str(dataset_path):
        raise ValueError(
            f"checkpoint dataset mismatch: checkpoint recorded {recorded!r} "
            f"but --dataset is {str(dataset_path)!r}"
        )
    processed = cp.get("items", [])
    return processed, {it["id"] for it in processed}


def run_eval(
    dataset_path: Path,
    backend_url: str,
    token: str,
    top_k: int,
    skip_judge: bool,
    out_dir: Path,
    match_window_s: float = DEFAULT_MATCH_WINDOW_S,
    metric_level: str = "episode",
    canary: int | None = None,
    persist_answers: bool = False,
    checkpoint_every: int = 0,
    resume_path: Path | None = None,
) -> dict:
    """Execute eval; return report dict + write JSON/MD to out_dir."""
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    show_id = data["show_id"]
    items = data["items"]
    if canary is not None:
        items = items[:canary]

    judge_fn = None
    judge_model = None
    if not skip_judge:
        try:
            try:
                from backend.eval.judge_config import PRODUCTION_JUDGE_MODEL
                from backend.eval.metrics.judge_metrics import judge_score
            except ModuleNotFoundError:
                from eval.judge_config import PRODUCTION_JUDGE_MODEL
                from eval.metrics.judge_metrics import judge_score
            judge_fn = judge_score
            judge_model = PRODUCTION_JUDGE_MODEL
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] judge unavailable ({exc}); continuing retrieval-only", file=sys.stderr)

    out_items: list[dict] = []
    processed_ids: set[str] = set()
    if resume_path is not None:
        out_items, processed_ids = _load_checkpoint(resume_path, dataset_path)
        print(f"[resume] skipping {len(processed_ids)} already-processed items from {resume_path}", file=sys.stderr)

    cp_path = _checkpoint_path(out_dir)
    run_config_meta = {
        "dataset": str(dataset_path),
        "backend_url": backend_url,
        "top_k": top_k,
        "metric_level": metric_level,
        "match_window_s": match_window_s,
        "canary": canary,
        "persist_answers": persist_answers,
        "checkpoint_every": checkpoint_every,
        "skip_judge": skip_judge,
    }

    for i, item in enumerate(items, 1):
        if item["id"] in processed_ids:
            continue
        eval_mode = item.get("eval_mode", "chunk_id")
        print(f"[{i}/{len(items)}] {item['id']} ({item['type']}, {eval_mode})…", file=sys.stderr)
        chunk_ids, chunk_texts, latency_ms = _retrieve(
            backend_url, show_id, item["question"], top_k, token,
        )

        rec: float | None
        rr: float | None
        ep_recall: float | None = None
        # eval-runner-chat-enum-scoring diagnostics — populated only on
        # enumeration items, included in the per-item record below.
        enum_episodes_count: int = 0
        ep_recall_chat_only: float | None = None

        if eval_mode == "enumeration":
            # Episode-set recall now unions search-side episode_ids (from
            # top-K chunks) with chat-side episode_ids (from
            # ChatResponse.enumeration_episodes). chat call fails open;
            # see _retrieve_chat_enumeration for contract.
            retrieved_eps_search = _to_episode_ids(chunk_ids)
            chat_eps, chat_total = _retrieve_chat_enumeration(
                backend_url, show_id, item["question"], token,
            )
            expected_eps = item.get("expected_episode_ids", [])
            retrieved_eps_union = list(set(retrieved_eps_search) | set(chat_eps))
            ep_recall = episode_set_recall(retrieved_eps_union, expected_eps)
            # Diagnostic split: chat_total is None on chat failure,
            # 0 when chat path didn't classify as enumeration, len(chat_eps) on success.
            if chat_total is None:
                enum_episodes_count = 0
                ep_recall_chat_only = None
            else:
                enum_episodes_count = chat_total
                ep_recall_chat_only = episode_set_recall(chat_eps, expected_eps)
            rec = None
            rr = None
        else:
            gt = item.get("ground_truth_chunk_ids", [])
            if metric_level == "episode":
                # Episode-level match: hit if any retrieved chunk shares episode_id
                # with any anchor (ignores start_time and `match_window_s`).
                retrieved_match = _to_episode_ids(chunk_ids)
                gt_match = _to_episode_ids(gt)
            else:
                # Chunk-level (legacy R1.2 / R3.1 behaviour) — bucket by window.
                retrieved_match = _to_lenient_ids(chunk_ids, match_window_s)
                gt_match = _to_lenient_ids(gt, match_window_s)
            if eval_mode == "open_set_lenient":
                # Any-anchor-hit → 1.0; otherwise 0.0 (treats partial matches as full credit).
                rec = 1.0 if (gt_match and set(retrieved_match) & set(gt_match)) else 0.0
            else:
                # chunk_id mode (legacy): fractional recall against full anchor set.
                rec = recall_at_k(retrieved_match, gt_match, k=top_k)
            rr = reciprocal_rank(retrieved_match, gt_match) if gt_match else None

        judge_val: float | None = None
        answer = ""
        ctx_texts: list[str] = []
        if judge_fn is not None:
            answer, ctx_texts = _query(backend_url, show_id, item["question"], token)
            if answer:
                # Use the actual /query retrieved context if available, else fall back to /search chunks.
                ctx = ctx_texts or chunk_texts
                try:
                    judge_val = judge_fn(item["question"], answer, ctx)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [warn] judge failed: {exc}", file=sys.stderr)

        record: dict = {
            "id": item["id"],
            "type": item["type"],
            "eval_mode": eval_mode,
            "recall_at_k": rec,
            "reciprocal_rank": rr,
            "episode_set_recall": ep_recall,
            "judge_score": judge_val,
            "latency_ms": round(latency_ms, 1),
        }
        # eval-runner-chat-enum-scoring: per-item diagnostic fields for
        # enumeration items only. Lets RCA tell search-only vs chat-only
        # path divergence apart from the union number.
        if eval_mode == "enumeration":
            record["enumeration_episodes_count"] = enum_episodes_count
            record["episode_set_recall_chat_only"] = ep_recall_chat_only
        if persist_answers:
            record["question"] = item["question"]
            record["retrieved_chunk_ids"] = chunk_ids
            record["retrieved_texts"] = [t[:4000] for t in chunk_texts]
            record["answer"] = answer
            record["retrieval_context_for_judge"] = ctx_texts or chunk_texts
        out_items.append(record)

        if checkpoint_every and len(out_items) % checkpoint_every == 0:
            _write_checkpoint_atomic(cp_path, {"meta": run_config_meta, "items": out_items})

    metrics = _aggregate(out_items)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "dataset": data["show_slug"],
        "version": data["version"],
        "run_id": run_id,
        "backend": backend_url,
        "judge_model": judge_model,
        "top_k": top_k,
        "metric_level": metric_level,
        "n_items": len(out_items),
        "metrics": metrics,
        "items": out_items,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".canary" if canary is not None else ""
    json_path = out_dir / f"eval-{data['show_slug']}-{run_id}{suffix}.json"
    md_path = out_dir / f"eval-{data['show_slug']}-{run_id}{suffix}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    if cp_path.exists():
        cp_path.unlink()
    print(f"\n[ok] report: {json_path}", file=sys.stderr)
    print(f"[ok] summary: {md_path}", file=sys.stderr)
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RAG eval against a backend")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("EVAL_AUTH_TOKEN", ""),
        help="Session cookie value (or env EVAL_AUTH_TOKEN). Optional but recommended.",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--match-window-s",
        type=float,
        default=DEFAULT_MATCH_WINDOW_S,
        help="Seconds. A retrieved chunk counts as a hit if its start_time is within "
        "this window of an anchor's start_time (same episode). Default 10s.",
    )
    parser.add_argument(
        "--metric-level",
        choices=["episode", "chunk"],
        default="episode",
        help="`episode`: hit if retrieved chunk's episode_id matches any anchor "
        "episode_id (R3.2 default, fair to description hits). `chunk`: legacy "
        "R1.2/R3.1 behaviour using start_time bucketing.",
    )
    parser.add_argument("--skip-judge", action="store_true", help="Retrieval metrics only")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "backend/eval/results",
    )
    parser.add_argument(
        "--canary",
        type=int,
        default=None,
        help="If set, process only the first N items (positive integer). For Phase 1 canary runs.",
    )
    parser.add_argument(
        "--persist-answers",
        action="store_true",
        help="Persist per-item question/answer/retrieved chunks for RCA. Off by default (lean output).",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=0,
        help="Write .checkpoint.json every N items (atomic). 0 = disabled.",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Path to .checkpoint.json from a previous interrupted run. Skips already-processed items.",
    )
    args = parser.parse_args(argv)

    if not args.dataset.exists():
        print(f"dataset not found: {args.dataset}", file=sys.stderr)
        return 2
    if args.canary is not None and args.canary <= 0:
        print("--canary must be a positive integer", file=sys.stderr)
        return 2
    if args.checkpoint_every < 0:
        print("--checkpoint-every must be >= 0", file=sys.stderr)
        return 2
    if args.canary is not None and args.resume is not None:
        print("--canary and --resume are mutually exclusive (resume is for full runs)", file=sys.stderr)
        return 2

    run_eval(
        dataset_path=args.dataset,
        backend_url=args.backend_url.rstrip("/"),
        token=args.auth_token,
        top_k=args.top_k,
        skip_judge=args.skip_judge,
        out_dir=args.out_dir,
        match_window_s=args.match_window_s,
        metric_level=args.metric_level,
        canary=args.canary,
        persist_answers=args.persist_answers,
        checkpoint_every=args.checkpoint_every,
        resume_path=args.resume,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
