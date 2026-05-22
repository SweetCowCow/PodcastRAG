"""Chat agent eval: compare rule-based vs agentic pipeline on the golden set.

Runs the golden set twice (or loads a baseline) and computes:
  - Recall@5 (via POST /search)
  - answer_match  (keyword hit-rate on expected_answer_keywords)

Gate thresholds (design.md Decision: Eval gate 在 roll-out 前):
  - Recall@5    : agentic must NOT drop > 5pp vs baseline
  - answer_match: agentic must NOT drop > 5pp vs baseline

Note on Faithfulness:
  Live LLM judge faithfulness is intentionally skipped here to keep the script
  free of additional API costs.  Run the standard `eval/runners/run.py` with
  `--auth-token` for a full faithfulness measurement; paste its judge_score_mean
  into the case study manually.

Usage (two-pass, same backend):
  1. Ensure ENABLE_AGENTIC_CHAT=false on the backend, then:
       python backend/scripts/run_chat_agent_eval.py \\
           --dataset backend/eval/datasets/this-not-that-cool.json \\
           --backend-url https://api.podcastrag.app \\
           --auth-token $TOKEN \\
           --label rule-based \\
           --out backend/eval/results/chat_eval_rule_based.json

  2. Set ENABLE_AGENTIC_CHAT=true on the backend, then:
       python backend/scripts/run_chat_agent_eval.py \\
           --dataset backend/eval/datasets/this-not-that-cool.json \\
           --backend-url https://api.podcastrag.app \\
           --auth-token $TOKEN \\
           --label agentic \\
           --baseline backend/eval/results/chat_eval_rule_based.json \\
           --out backend/eval/results/chat_eval_agentic.json

  The second run prints the comparison table and writes
  docs/case-studies/agentic-chat-eval-<YYYY-MM>.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
_GATE_RECALL_PP = 5.0
_GATE_ANSWER_MATCH_PP = 5.0
_CITATION_RE = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")

# ────────────────────────────────────────────────────────────────────
# HTTP helpers (mirror run.py pattern; no third-party deps)
# ────────────────────────────────────────────────────────────────────

_CSRF_CACHE: dict[str, str] = {}
_ORIGIN_OVERRIDE: str | None = None


def _fetch_csrf(backend_url: str, token: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(
        f"{backend_url}/me", headers={"Cookie": f"session_id={token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()).get("csrf_token", "") or ""
    except (urllib.error.URLError, json.JSONDecodeError):
        return ""


def _post(url: str, body: dict, token: str, timeout: float = 60.0) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Cookie"] = f"session_id={token}"
        if token not in _CSRF_CACHE:
            p = urlparse(url)
            root = f"{p.scheme}://{p.netloc}"
            _CSRF_CACHE[token] = _fetch_csrf(root, token)
        csrf = _CSRF_CACHE.get(token, "")
        if csrf:
            headers["X-CSRF-Token"] = csrf
            if _ORIGIN_OVERRIDE:
                headers["Origin"] = _ORIGIN_OVERRIDE
            else:
                headers["Origin"] = urlparse(url).scheme + "://" + urlparse(url).netloc
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_exc = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))  # 2s, 4s
                continue
            raise
    raise last_exc  # unreachable, for type-checker


def _search(backend_url: str, show_id: str, question: str, k: int, token: str) -> list[str]:
    """Return top-k chunk_ids from the search endpoint."""
    try:
        resp = _post(
            f"{backend_url}/shows/{show_id}/search",
            {"question": question, "k": k},
            token,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"  [warn] search failed: {exc}", file=sys.stderr)
        return []
    hits = resp.get("results", [])
    return [f"ep:{h['episode_id']}@{float(h['start_time']):.2f}" for h in hits]


def _query_chat(backend_url: str, show_id: str, question: str, token: str) -> str:
    """Return the chat answer text (inline citations stripped)."""
    try:
        resp = _post(
            f"{backend_url}/shows/{show_id}/query",
            {"question": question, "mode": "chat", "messages": []},
            token,
            timeout=90.0,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"  [warn] query failed: {exc}", file=sys.stderr)
        return ""
    raw = resp.get("answer") or ""
    return _CITATION_RE.sub("", raw).strip()


def _query_chat_with_trace(
    backend_url: str,
    show_id: str,
    question: str,
    token: str,
    *,
    session_id: str | None = None,
    messages: list[dict] | None = None,
) -> dict:
    """POST /query?debug_trace=true returning the full response body.

    Caller is responsible for being authenticated as an admin (the
    backdoor account is admin by construction). Returns `{}` on transport
    failure so the runner keeps going.
    """
    body: dict = {"question": question, "mode": "chat", "messages": messages or []}
    if session_id:
        body["session_id"] = session_id
    try:
        resp = _post(
            f"{backend_url}/shows/{show_id}/query?debug_trace=true",
            body,
            token,
            timeout=120.0,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"  [warn] query failed: {exc}", file=sys.stderr)
        return {}
    return resp


# ────────────────────────────────────────────────────────────────────
# Scoring
# ────────────────────────────────────────────────────────────────────

_MATCH_WINDOW_S = 10.0


def _bucket(chunk_id: str) -> tuple[str, int]:
    try:
        head, tail = chunk_id.split("@", 1)
        return (head.removeprefix("ep:"), int(float(tail) // _MATCH_WINDOW_S))
    except (ValueError, IndexError):
        return ("", -1)


def _recall_at_k(retrieved: list[str], ground_truth: list[str], k: int) -> float | None:
    if not ground_truth:
        return None
    gt_buckets = {_bucket(c) for c in ground_truth}
    hit_count = sum(1 for c in retrieved[:k] if _bucket(c) in gt_buckets)
    return min(hit_count / len(ground_truth), 1.0)


def _answer_match(answer: str, keywords: list[str]) -> float:
    """Fraction of expected keywords found in the answer (case-insensitive)."""
    if not keywords:
        return 1.0
    answer_lower = answer.lower()
    hits = sum(1 for kw in keywords if kw.lower() in answer_lower)
    return hits / len(keywords)


# ────────────────────────────────────────────────────────────────────
# Main eval loop
# ────────────────────────────────────────────────────────────────────

def _is_nested_schema(items: list[dict]) -> bool:
    """Detect the extended-multi-turn-40 nested schema vs the legacy flat one."""
    return bool(items) and isinstance(items[0].get("turns"), list)


def _tool_coverage(
    tool_calls_made: list[str],
    required: list[str],
    acceptable: list[str],
) -> dict:
    """Compute per-turn tool-coverage flags.

    `required_hit` is 1.0 iff every name in `required` appears in
    `tool_calls_made`; `acceptable_hit` is 1.0 iff at least one
    `acceptable` name appears (or if `acceptable` is empty, vacuously
    `None`).
    """
    made = set(tool_calls_made)
    req_hit = 1.0 if required and all(t in made for t in required) else (
        1.0 if not required else 0.0
    )
    if acceptable:
        acc_hit = 1.0 if any(t in made for t in acceptable) else 0.0
    else:
        acc_hit = None
    return {"required_hit": req_hit, "acceptable_hit": acc_hit}


def _run_nested_eval(
    items: list[dict],
    show_id: str,
    backend_url: str,
    auth_token: str,
    top_k: int,
) -> tuple[list[dict], list[dict]]:
    """Run the eval over the nested (multi-turn) schema.

    Returns (per_turn_results, per_item_results). Multi-turn items share
    one `session_id` so the agent's L1 state carries between turns; each
    turn after the first sends prior `(question, answer)` pairs in
    `messages` so the model has chat history regardless of L1 state TTL.
    """
    import uuid as _uuid

    per_turn: list[dict] = []
    per_item: list[dict] = []
    for i, item in enumerate(items, 1):
        item_id = item["id"]
        is_multi = bool(item.get("is_multi_turn"))
        session_id = str(_uuid.uuid4())
        messages: list[dict] = []
        item_turns: list[dict] = []
        for t_idx, turn in enumerate(item["turns"], 1):
            question = turn["question"]
            expected_kws = turn.get("expected_answer_keywords", [])
            required = turn.get("expected_tool_calls_required", []) or []
            acceptable = turn.get("expected_tool_calls_acceptable", []) or []
            print(f"  [{i:02d}/{len(items)}] {item_id} turn {t_idx}/{len(item['turns'])}")

            gt_chunks = turn.get("ground_truth_chunk_ids")
            recall_at_k: float | None = None
            if isinstance(gt_chunks, list) and gt_chunks:
                retrieved = _search(backend_url, show_id, question, top_k, auth_token)
                recall_at_k = _recall_at_k(retrieved, gt_chunks, top_k)

            t0 = time.monotonic()
            resp = _query_chat_with_trace(
                backend_url,
                show_id,
                question,
                auth_token,
                session_id=session_id,
                messages=messages,
            )
            latency_ms = (time.monotonic() - t0) * 1000

            raw_answer = resp.get("answer") or ""
            answer = _CITATION_RE.sub("", raw_answer).strip()
            am = _answer_match(answer, expected_kws)
            tool_names = [
                tc.get("name", "") for tc in (resp.get("tool_calls") or [])
            ]
            cov = _tool_coverage(tool_names, required, acceptable)

            turn_result = {
                "item_id": item_id,
                "turn_index": t_idx,
                "is_multi_turn": is_multi,
                "design_type": item.get("design_type", "unknown"),
                "recall_at_k": recall_at_k,
                "answer_match": am,
                "tool_required_hit": cov["required_hit"],
                "tool_acceptable_hit": cov["acceptable_hit"],
                "tool_calls_made": tool_names,
                "answer": answer[:300],
                "latency_ms": round(latency_ms, 1),
            }
            per_turn.append(turn_result)
            item_turns.append(turn_result)

            messages.append({"role": "user", "content": question})
            messages.append({"role": "assistant", "content": answer})

        item_am_mean = mean([t["answer_match"] for t in item_turns])
        item_required_mean = mean([t["tool_required_hit"] for t in item_turns])
        per_item.append({
            "id": item_id,
            "is_multi_turn": is_multi,
            "design_type": item.get("design_type", "unknown"),
            "n_turns": len(item_turns),
            "answer_match_mean": round(item_am_mean, 4),
            "tool_required_hit_mean": round(item_required_mean, 4),
        })
    return per_turn, per_item


def run_eval(
    dataset_path: Path,
    backend_url: str,
    auth_token: str,
    top_k: int,
    label: str,
) -> dict:
    dataset = json.loads(dataset_path.read_text())
    show_id = dataset["show_id"]
    items = dataset["items"]

    if _is_nested_schema(items):
        per_turn, per_item = _run_nested_eval(
            items, show_id, backend_url, auth_token, top_k
        )
        scored_am = [t["answer_match"] for t in per_turn]
        scored_req = [t["tool_required_hit"] for t in per_turn]
        scored_acc = [t["tool_acceptable_hit"] for t in per_turn if t["tool_acceptable_hit"] is not None]
        scored_recall = [t["recall_at_k"] for t in per_turn if t.get("recall_at_k") is not None]
        multi_turn_items = [it for it in per_item if it["is_multi_turn"]]
        aggregate = {
            "schema": "nested-multi-turn",
            "n_items": len(per_item),
            "n_turns": len(per_turn),
            "n_multi_turn_items": len(multi_turn_items),
            "recall_at_k_mean": round(mean(scored_recall), 4) if scored_recall else None,
            "n_scored_recall": len(scored_recall),
            "answer_match_mean": round(mean(scored_am), 4) if scored_am else None,
            "tool_required_hit_mean": round(mean(scored_req), 4) if scored_req else None,
            "tool_acceptable_hit_mean": (
                round(mean(scored_acc), 4) if scored_acc else None
            ),
        }
        return {
            "label": label,
            "dataset": str(dataset_path),
            "show_id": show_id,
            "top_k": top_k,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "aggregate": aggregate,
            "turns": per_turn,
            "items": per_item,
        }

    # Legacy flat schema (this-not-that-cool.json)
    results = []
    for i, item in enumerate(items, 1):
        qid = item["id"]
        question = item["question"]
        expected_kws = item.get("expected_answer_keywords", [])
        gt_chunks = item.get("ground_truth_chunk_ids", [])
        print(f"  [{i:02d}/{len(items)}] {qid}")

        # Recall@5 via search
        retrieved = _search(backend_url, show_id, question, top_k, auth_token)
        r5 = _recall_at_k(retrieved, gt_chunks, top_k)

        # Answer quality via chat
        t0 = time.monotonic()
        answer = _query_chat(backend_url, show_id, question, auth_token)
        latency_ms = (time.monotonic() - t0) * 1000

        am = _answer_match(answer, expected_kws)

        results.append({
            "id": qid,
            "type": item.get("type", "unknown"),
            "recall_at_k": r5,
            "answer_match": am,
            "answer": answer[:300],
            "latency_ms": round(latency_ms, 1),
        })

    # Aggregate
    scored_r5 = [r["recall_at_k"] for r in results if r["recall_at_k"] is not None]
    scored_am = [r["answer_match"] for r in results]
    aggregate = {
        "schema": "flat",
        "n": len(results),
        "n_scored_recall": len(scored_r5),
        "recall_at_k_mean": round(mean(scored_r5), 4) if scored_r5 else None,
        "answer_match_mean": round(mean(scored_am), 4) if scored_am else None,
    }

    return {
        "label": label,
        "dataset": str(dataset_path),
        "show_id": show_id,
        "top_k": top_k,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "aggregate": aggregate,
        "items": results,
    }


# ────────────────────────────────────────────────────────────────────
# Gate check + comparison table
# ────────────────────────────────────────────────────────────────────

def _compare(baseline: dict, current: dict) -> dict:
    ba = baseline["aggregate"]
    ca = current["aggregate"]

    r5_base = ba.get("recall_at_k_mean") or 0.0
    r5_curr = ca.get("recall_at_k_mean") or 0.0
    am_base = ba.get("answer_match_mean") or 0.0
    am_curr = ca.get("answer_match_mean") or 0.0

    r5_delta_pp = (r5_curr - r5_base) * 100
    am_delta_pp = (am_curr - am_base) * 100

    gate_recall_pass = r5_delta_pp >= -_GATE_RECALL_PP
    gate_am_pass = am_delta_pp >= -_GATE_ANSWER_MATCH_PP
    overall_pass = gate_recall_pass and gate_am_pass

    return {
        "baseline_label": baseline["label"],
        "current_label": current["label"],
        "recall_at_k": {
            "baseline": r5_base,
            "current": r5_curr,
            "delta_pp": round(r5_delta_pp, 2),
            "gate_pass": gate_recall_pass,
        },
        "answer_match": {
            "baseline": am_base,
            "current": am_curr,
            "delta_pp": round(am_delta_pp, 2),
            "gate_pass": gate_am_pass,
        },
        "overall_gate_pass": overall_pass,
    }


def _print_comparison(cmp: dict) -> None:
    print("\n" + "=" * 60)
    print(f"Pipeline comparison: {cmp['baseline_label']} → {cmp['current_label']}")
    print("=" * 60)
    for metric in ("recall_at_k", "answer_match"):
        m = cmp[metric]
        status = "✓ PASS" if m["gate_pass"] else "✗ FAIL"
        print(
            f"  {metric:20s}  baseline={m['baseline']:.4f}  "
            f"current={m['current']:.4f}  Δ={m['delta_pp']:+.2f}pp  {status}"
        )
    overall = "✓ GATE PASSED" if cmp["overall_gate_pass"] else "✗ GATE FAILED"
    print(f"\n  {overall}\n")
    if not cmp["overall_gate_pass"]:
        print(
            "  ENABLE_AGENTIC_CHAT default MUST NOT be flipped until gate is met\n"
            "  or a stakeholder waiver is recorded in the case study.",
            file=sys.stderr,
        )


def _write_case_study(
    baseline: dict,
    current: dict,
    cmp: dict,
    out_dir: Path,
) -> Path:
    now = datetime.now(timezone.utc)
    fname = f"agentic-chat-eval-{now.strftime('%Y-%m')}.md"
    path = out_dir / fname
    gate_emoji = "✅" if cmp["overall_gate_pass"] else "❌"
    lines = [
        f"# Agentic Chat Eval — {now.strftime('%Y-%m-%d')}",
        "",
        "## Summary",
        "",
        "| Metric | Rule-based | Agentic | Δ (pp) | Gate |",
        "|--------|-----------|---------|--------|------|",
        _table_row("Recall@5", cmp["recall_at_k"], _GATE_RECALL_PP),
        _table_row("answer_match", cmp["answer_match"], _GATE_ANSWER_MATCH_PP),
        "",
        f"**Overall gate: {gate_emoji} {'PASS' if cmp['overall_gate_pass'] else 'FAIL'}**",
        "",
        "> Faithfulness (LLM judge): run `eval/runners/run.py --auth-token $TOKEN`",
        "> and paste `judge_score_mean` here before flipping the default.",
        "",
        "## Gate Decision",
        "",
        f"- Recall@5 gate (≤ {_GATE_RECALL_PP}pp drop): "
        f"{'PASS' if cmp['recall_at_k']['gate_pass'] else 'FAIL'}",
        f"- answer_match gate (≤ {_GATE_ANSWER_MATCH_PP}pp drop): "
        f"{'PASS' if cmp['answer_match']['gate_pass'] else 'FAIL'}",
        "",
        "## Raw Data",
        "",
        f"- Baseline (`{baseline['label']}`): `{baseline.get('timestamp', 'N/A')}`",
        f"- Agentic  (`{current['label']}`): `{current.get('timestamp', 'N/A')}`",
        f"- Dataset: `{baseline['dataset']}`",
        f"- Top-k: {baseline['top_k']}",
        "",
    ]
    path.write_text("\n".join(lines))
    return path


def _table_row(name: str, m: dict, gate_pp: float) -> str:
    status = "✅" if m["gate_pass"] else "❌"
    return (
        f"| {name} | {m['baseline']:.4f} | {m['current']:.4f} | "
        f"{m['delta_pp']:+.2f}pp | {status} (gate ≤{gate_pp}pp drop) |"
    )


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chat agent eval: compare rule-based vs agentic")
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--backend-url", required=True)
    p.add_argument("--auth-token", default="")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--label", default="agentic", help="Label for this run (e.g. 'rule-based' or 'agentic')")
    p.add_argument("--out", type=Path, required=True, help="Write JSON results to this file")
    p.add_argument("--baseline", type=Path, default=None, help="Baseline JSON from a previous rule-based run")
    p.add_argument("--origin", default=None, help="Override Origin header (default: derive from backend-url)")
    p.add_argument(
        "--case-study-dir",
        type=Path,
        default=REPO_ROOT / "docs" / "case-studies",
        help="Directory for the case study markdown (default: docs/case-studies/)",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    global _ORIGIN_OVERRIDE
    if args.origin:
        _ORIGIN_OVERRIDE = args.origin

    print(f"Running chat eval: {args.label}")
    print(f"  dataset   : {args.dataset}")
    print(f"  backend   : {args.backend_url}")
    print(f"  top-k     : {args.top_k}")

    result = run_eval(
        dataset_path=args.dataset,
        backend_url=args.backend_url,
        auth_token=args.auth_token,
        top_k=args.top_k,
        label=args.label,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    agg = result["aggregate"]
    print(
        f"\nResults [{args.label}]:"
        f"  Recall@{args.top_k}={agg.get('recall_at_k_mean')}  "
        f"answer_match={agg.get('answer_match_mean')}"
    )
    print(f"  → saved to {args.out}")

    if args.baseline:
        baseline = json.loads(args.baseline.read_text())
        cmp = _compare(baseline, result)
        _print_comparison(cmp)

        cs_path = _write_case_study(baseline, result, cmp, args.case_study_dir)
        print(f"  → case study written to {cs_path}")

        if not cmp["overall_gate_pass"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
