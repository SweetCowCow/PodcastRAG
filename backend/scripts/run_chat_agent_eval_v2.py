"""Chat-rag v2 eval runner.

Usage:
    python -m backend.scripts.run_chat_agent_eval_v2 \\
        --dataset backend/eval/datasets/extended-multi-turn-40.v2.json \\
        --backend https://podcastrag-api.zeabur.app \\
        --session-cookie-file /tmp/podcastrag_session.txt \\
        --me-json /tmp/me_resp.json \\
        --filter-ids b22,b27,b29,b11,b15,b14,mt01 \\
        --output /tmp/v2-baseline.json \\
        --report /tmp/v2-baseline.md

For each filtered item:
- POST {backend}/shows/{show_id}/query?debug_trace=true (multi-turn: chain session_id)
- Invoke chat_judge_v2 once per item, stash verdict under agent_response['_judge_verdict']
- Run all plugin graders + judge-derived indicators
- Aggregate by design_type + indicator
- Write JSON + Markdown report (with judge_prompt_sha256)

This is a minimal end-to-end runner. It does NOT replace backend/scripts/run_chat_agent_eval.py
for the legacy v1 dataset; that runner keeps its own dispatch path. The v2 file is the
contract for schema_version 2.0 datasets.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.eval.graders.loader import discover_graders
from backend.eval.judge_chat_v2 import build_payload, invoke_judge, load_prompt_sha256
from backend.eval.runner_v2_aggregate import (
    aggregate,
    dataset_schema_version,
    render_markdown,
)

CITATION_FIX_COMMIT = "287e73b"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _citation_fix_applied(prod_commit: str | None, confirm_flag: bool) -> bool:
    """Decide whether prod backend includes the `_AGENTIC_SEARCH_TOOLS` whitelist fix.

    Uses `git merge-base --is-ancestor 287e73b <commit>` when commit is available and
    falls back to the `--citation-fix-confirmed` flag when git context is missing.
    """
    if confirm_flag:
        return True
    if not prod_commit:
        return False
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", CITATION_FIX_COMMIT, prod_commit],
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _build_provenance(
    *,
    prod_commit: str | None,
    citation_fix_confirmed: bool,
    dataset_path: Path,
    dataset_schema_version_str: str,
    run_started_at: str,
    run_completed_at: str,
) -> dict[str, Any]:
    return {
        "backend_commit": prod_commit or "unknown",
        "dataset_path": str(dataset_path),
        "dataset_schema_version": dataset_schema_version_str,
        "run_started_at": run_started_at,
        "run_completed_at": run_completed_at,
        "citation_collector_fix_applied": _citation_fix_applied(
            prod_commit, citation_fix_confirmed
        ),
    }


def _write_output(
    output_path: Path,
    *,
    results: list[dict[str, Any]],
    aggregate_report: dict[str, Any],
    judge_model: str,
    judge_sha: str,
    provenance: dict[str, Any],
) -> None:
    payload = {
        "schema_version": "2.0",
        "provenance": provenance,
        "judge_prompt_sha256": judge_sha,
        "judge_model": judge_model,
        "n_items": len(results),
        "results": results,
        "aggregate": aggregate_report,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _post_query(
    backend: str,
    show_id: str,
    question: str,
    *,
    cookie_header: str,
    csrf_header: str,
    session_id: str | None,
    messages: list[dict],
    timeout: float = 120.0,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "question": question,
        "mode": "chat",
        "messages": messages,
    }
    if session_id:
        body["session_id"] = session_id

    req = urllib.request.Request(
        f"{backend}/shows/{show_id}/query?debug_trace=true",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Cookie": cookie_header,
            "X-CSRF-Token": csrf_header,
            "Origin": "https://app.podcastrag.app",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _read_session_and_csrf(cookie_file: Path, me_json: Path) -> tuple[str, str]:
    parts: list[str] = []
    for line in cookie_file.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            # netscape cookie file may have leading # for HttpOnly; keep those
            if line.startswith("#HttpOnly_"):
                fields = line[len("#HttpOnly_"):].split("\t")
            else:
                continue
        else:
            fields = line.split("\t")
        if len(fields) >= 7:
            parts.append(f"{fields[5]}={fields[6]}")
    cookie_header = "; ".join(parts)
    csrf = json.loads(me_json.read_text(encoding="utf-8"))["csrf_token"]
    return cookie_header, csrf


def _items_indexed(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["id"]: i for i in dataset.get("items", [])}


def _run_one_item(
    item: dict[str, Any],
    *,
    backend: str,
    show_id: str,
    cookie_header: str,
    csrf_header: str,
    judge_model: str | None,
    extra_kwargs_by_grader: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Returns {'item_id', 'design_type', 'indicators': {...}, 'agent_response_summary': {...}}"""
    is_mt = bool(item.get("is_multi_turn"))
    session_id = str(uuid.uuid4()) if is_mt else None
    messages: list[dict] = []
    agent_responses: list[dict[str, Any]] = []
    turns = item.get("turns") if is_mt else [{"question": item.get("question"), **item}]

    for turn in turns:
        question = turn.get("question") or item.get("question")
        resp = _post_query(
            backend,
            show_id,
            question,
            cookie_header=cookie_header,
            csrf_header=csrf_header,
            session_id=session_id,
            messages=list(messages),
        )
        agent_responses.append(resp)
        if is_mt:
            messages.append({"role": "user", "content": question})
            messages.append({"role": "assistant", "content": resp.get("answer", "")})

    # For grading: focus on the LAST turn's response (mt assessment falls on t2)
    final_resp = agent_responses[-1]

    # Invoke LLM judge once for the final turn
    turn_scope = turns[-1] if is_mt else None
    payload = build_payload(item, final_resp, turn_scope=turn_scope)
    judge_verdict = invoke_judge(payload, model=judge_model)
    final_resp["_judge_verdict"] = judge_verdict

    # Run all plugin graders
    indicators: dict[str, dict[str, Any] | None] = {}
    graders = discover_graders()
    for name, fn in graders.items():
        try:
            kwargs = extra_kwargs_by_grader.get(name, {})
            if name == "ordinal_resolution" and is_mt and len(agent_responses) >= 2:
                kwargs = {
                    "prior_turn_context": {
                        "enumeration_episodes": agent_responses[-2].get("enumeration_episodes") or []
                    },
                    "current_turn_index": len(turns) - 1,
                }
            indicators[name] = fn(item, final_resp, **kwargs)
        except TypeError:
            indicators[name] = fn(item, final_resp)
        except Exception as e:  # noqa: BLE001
            indicators[name] = {"score": None, "passed": False, "details": {"error": str(e)[:200]}}

    # Layer in judge-derived top-level scores (factual_correctness, refusal_appropriateness)
    fc = judge_verdict.get("factual_correctness") or {}
    if fc.get("score") is not None:
        indicators["factual_correctness"] = {
            "score": fc["score"],
            "passed": fc["score"] >= 0.7,
            "details": {"rationale": fc.get("rationale")},
        }
    ra = judge_verdict.get("refusal_appropriateness") or {}
    if ra.get("verdict") and ra.get("verdict") != "error":
        passed_ra = ra.get("verdict") == "appropriate"
        indicators["refusal_appropriateness"] = {
            "score": 1.0 if passed_ra else 0.0,
            "passed": passed_ra,
            "details": {
                "verdict": ra.get("verdict"),
                "is_refusal_with_correction": ra.get("is_refusal_with_correction"),
                "rationale": ra.get("rationale"),
            },
        }

    return {
        "item_id": item["id"],
        "design_type": item.get("design_type"),
        "indicators": indicators,
        "agent_responses_meta": [
            {
                "turn_idx": i,
                "answer_preview": (r.get("answer") or "")[:160],
                "tool_calls_n": len(r.get("tool_calls") or []),
                "enumeration_total": r.get("enumeration_total"),
                "unverified_count": r.get("unverified_count"),
            }
            for i, r in enumerate(agent_responses)
        ],
        "judge_verdict": judge_verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--backend", required=True)
    ap.add_argument("--session-cookie-file", required=True)
    ap.add_argument("--me-json", required=True)
    ap.add_argument("--filter-ids", default="")
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--judge-model", default=None)
    ap.add_argument(
        "--prod-commit",
        default=None,
        help="Prod backend git commit hash this eval is being run against. "
        "Recorded in output provenance. Used to derive citation_collector_fix_applied.",
    )
    ap.add_argument(
        "--citation-fix-confirmed",
        action="store_true",
        help="Explicitly assert that the prod backend includes commit 287e73b "
        "(citation collector fix). Fallback when --prod-commit cannot be checked "
        "via git merge-base.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file if it already exists. Default refuses.",
    )
    args = ap.parse_args()

    output_path = Path(args.output)
    if output_path.exists() and not args.force:
        print(
            f"existing baseline at {output_path}; pass --force to overwrite",
            file=sys.stderr,
        )
        return 2

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    schema_version_str = dataset_schema_version(dataset)
    if schema_version_str != "2.0":
        print(
            f"[warn] dataset schema_version != 2.0; aborting",
            file=sys.stderr,
        )
        return 2

    show_id = dataset["show_id"]
    by_id = _items_indexed(dataset)
    if args.filter_ids:
        ids = [s.strip() for s in args.filter_ids.split(",") if s.strip()]
        items = [by_id[i] for i in ids if i in by_id]
    else:
        items = dataset["items"]

    cookie_header, csrf_header = _read_session_and_csrf(
        Path(args.session_cookie_file), Path(args.me_json)
    )

    judge_sha = load_prompt_sha256()
    judge_model = args.judge_model or "PRODUCTION_JUDGE_MODEL default"
    run_started_at = _utc_now_iso()
    results: list[dict[str, Any]] = []
    interrupted = False
    failure: Exception | None = None
    try:
        for idx, item in enumerate(items, 1):
            start = time.time()
            print(
                f"[{idx}/{len(items)}] {item['id']} ({item['design_type']}) ...",
                flush=True,
            )
            try:
                res = _run_one_item(
                    item,
                    backend=args.backend,
                    show_id=show_id,
                    cookie_header=cookie_header,
                    csrf_header=csrf_header,
                    judge_model=args.judge_model,
                    extra_kwargs_by_grader={},
                )
                results.append(res)
                print(f"   done in {time.time() - start:.1f}s", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"   FAILED: {e}", file=sys.stderr)
                results.append(
                    {
                        "item_id": item["id"],
                        "design_type": item.get("design_type"),
                        "indicators": {},
                        "error": str(e)[:300],
                    }
                )
    except KeyboardInterrupt:
        interrupted = True
        print("\n[interrupt] writing partial output with provenance...", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        failure = e
        print(f"\n[fatal] {e}; writing partial output", file=sys.stderr)

    run_completed_at = _utc_now_iso()
    provenance = _build_provenance(
        prod_commit=args.prod_commit,
        citation_fix_confirmed=args.citation_fix_confirmed,
        dataset_path=Path(args.dataset),
        dataset_schema_version_str=schema_version_str,
        run_started_at=run_started_at,
        run_completed_at=run_completed_at,
    )

    agg = aggregate(results) if results else {"by_design_type": {}, "overall": {}}
    title_suffix = " (partial)" if (interrupted or failure) else ""
    _write_output(
        output_path,
        results=results,
        aggregate_report=agg,
        judge_model=judge_model,
        judge_sha=judge_sha,
        provenance=provenance,
    )
    Path(args.report).write_text(
        render_markdown(
            agg,
            title=f"Chat-RAG v2 baseline ({Path(args.dataset).name}, n={len(results)}){title_suffix}",
            judge_prompt_sha256=judge_sha,
        ),
        encoding="utf-8",
    )
    print(f"\n✓ wrote {args.output} + {args.report}")
    if failure:
        raise failure
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
