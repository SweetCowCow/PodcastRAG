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
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from backend.eval.graders.loader import discover_graders
from backend.eval.judge_chat_v2 import build_payload, invoke_judge, load_prompt_sha256
from backend.eval.runner_v2_aggregate import (
    aggregate,
    dataset_schema_version,
    render_markdown,
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
    args = ap.parse_args()

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    if dataset_schema_version(dataset) != "2.0":
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

    results: list[dict[str, Any]] = []
    for idx, item in enumerate(items, 1):
        start = time.time()
        print(f"[{idx}/{len(items)}] {item['id']} ({item['design_type']}) ...", flush=True)
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

    agg = aggregate(results)
    judge_sha = load_prompt_sha256()
    Path(args.output).write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "judge_prompt_sha256": judge_sha,
                "judge_model": args.judge_model or "PRODUCTION_JUDGE_MODEL default",
                "n_items": len(results),
                "results": results,
                "aggregate": agg,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    Path(args.report).write_text(
        render_markdown(
            agg,
            title=f"Chat-RAG v2 baseline ({Path(args.dataset).name}, n={len(results)})",
            judge_prompt_sha256=judge_sha,
        ),
        encoding="utf-8",
    )
    print(f"\n✓ wrote {args.output} + {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
