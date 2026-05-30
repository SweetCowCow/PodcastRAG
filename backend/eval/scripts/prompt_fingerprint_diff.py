"""Prompt fingerprint diff — compare agent search_query drift across two backends.

Background: 2026-05-28 step1-idf-and-prefilter Layer B failed because the
prompt change subtly altered the agent's `search_within_episode(query: str)`
queries (the LLM rephrased queries given the new few-shot examples), and
`ts_rank` followed those new phrasings into different top-K chunks. Prompt
changes are NEVER orthogonal to retrieval. This CLI captures that drift
mechanically.

Approach:
  For each (item, turn) in the dataset, POST to both backends with
  ?debug_trace=true, extract the first `search_*` tool call's `query`
  argument, and print a markdown diff table.

Usage:
    python -m backend.eval.scripts.prompt_fingerprint_diff \\
        --old-backend https://podcastrag-api.zeabur.app \\
        --new-backend https://podcastrag-api-pr-preview.zeabur.app \\
        --dataset backend/eval/datasets/_calibration_8.json \\
        --session-cookie-file /tmp/podcastrag_session.txt \\
        --me-json /tmp/me_resp.json \\
        --output /tmp/prompt-fingerprint-diff.md

Source design (Decision 5): "對兩個 commit 各跑 chat eval → SQL query
eval_traces 抓 search_query per (item_id, turn_idx)". This script
implements the same idea but reads search_query from each backend's
`?debug_trace=true` response inline rather than from eval_traces SQL —
faster, no eval_context plumbing dependency, functionally equivalent for
PR-time use. The SQL eval_traces path remains canonical for archival
RCA (cross-run comparisons over weeks/months).

Optional `--source=sql --run-id-old=... --run-id-new=...` will be wired
once the runner emits eval_context (item_id, turn_idx) into spans.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / "backend" / ".env")


def _read_cookie_csrf(cookie_file: Path, me_json: Path) -> tuple[str, str]:
    parts: list[str] = []
    for line in cookie_file.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
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


def _extract_search_queries(resp: dict[str, Any]) -> list[tuple[str, str]]:
    """Return list of (tool_name, query_str) for every search_* tool call."""
    tool_calls = resp.get("tool_calls") or (resp.get("debug_trace") or {}).get("tool_calls") or []
    out: list[tuple[str, str]] = []
    for tc in tool_calls:
        name = tc.get("tool_name") or tc.get("name") or ""
        if not name.startswith("search_"):
            continue
        args = tc.get("tool_args") or tc.get("args") or {}
        q = args.get("query") if isinstance(args, dict) else None
        if q:
            out.append((name, str(q)))
    return out


def _run_eval_for_backend(
    backend: str,
    items: list[dict],
    show_id: str,
    cookie_header: str,
    csrf_header: str,
) -> dict[tuple[str, int], list[tuple[str, str]]]:
    """Returns {(item_id, turn_idx): [(tool_name, query_str), ...]}."""
    out: dict[tuple[str, int], list[tuple[str, str]]] = {}
    for item in items:
        is_mt = bool(item.get("is_multi_turn"))
        session_id = str(uuid.uuid4()) if is_mt else None
        messages: list[dict] = []
        turns = item.get("turns") if is_mt else [{"question": item.get("question")}]
        for turn_idx, turn in enumerate(turns):
            question = turn.get("question") or item.get("question")
            print(f"  [{backend}] {item['id']} turn={turn_idx} ...", flush=True)
            resp = _post_query(
                backend,
                show_id,
                question,
                cookie_header=cookie_header,
                csrf_header=csrf_header,
                session_id=session_id,
                messages=list(messages),
            )
            out[(item["id"], turn_idx)] = _extract_search_queries(resp)
            if is_mt:
                messages.append({"role": "user", "content": question})
                messages.append({"role": "assistant", "content": resp.get("answer", "")})
    return out


def _render_diff_markdown(
    old: dict[tuple[str, int], list[tuple[str, str]]],
    new: dict[tuple[str, int], list[tuple[str, str]]],
    old_backend: str,
    new_backend: str,
) -> str:
    rows: list[str] = []
    rows.append(f"# Prompt fingerprint diff\n")
    rows.append(f"- old: `{old_backend}`")
    rows.append(f"- new: `{new_backend}`\n")
    rows.append("| item | turn | tool | old query | new query | changed? |")
    rows.append("|---|---|---|---|---|---|")
    keys = sorted(set(old.keys()) | set(new.keys()))
    changed = 0
    same = 0
    for key in keys:
        item_id, turn_idx = key
        old_calls = old.get(key) or []
        new_calls = new.get(key) or []
        max_n = max(len(old_calls), len(new_calls), 1)
        for i in range(max_n):
            o = old_calls[i] if i < len(old_calls) else ("-", "")
            n = new_calls[i] if i < len(new_calls) else ("-", "")
            tool_label = o[0] if o[0] != "-" else n[0]
            old_q = o[1].replace("|", "\\|")[:60]
            new_q = n[1].replace("|", "\\|")[:60]
            is_changed = o[1] != n[1]
            if is_changed:
                changed += 1
                marker = "❗"
            else:
                same += 1
                marker = "✓"
            rows.append(
                f"| {item_id} | {turn_idx} | {tool_label} | "
                f"`{old_q}` | `{new_q}` | {marker} |"
            )
    rows.append("")
    rows.append(f"**Summary**: {changed} changed, {same} unchanged "
                f"(total {changed + same} search_* tool calls)")
    return "\n".join(rows) + "\n"


async def _load_from_sql(
    run_id: str,
) -> dict[tuple[str, int], list[tuple[str, str]]]:
    """SQL path: SELECT search_query per (item_id, turn_idx, tool_name)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    out: dict[tuple[str, int], list[tuple[str, str]]] = {}
    try:
        async with Session() as db:
            rows = (await db.execute(
                text(
                    """
                    SELECT item_id, turn_idx, tool_name, search_query, started_at
                    FROM eval_traces
                    WHERE run_id = :run_id
                      AND tool_name IS NOT NULL
                      AND search_query IS NOT NULL
                    ORDER BY item_id, turn_idx, started_at
                    """
                ),
                {"run_id": run_id},
            )).all()
    finally:
        await engine.dispose()
    for r in rows:
        key = (r.item_id, int(r.turn_idx))
        out.setdefault(key, []).append((r.tool_name, r.search_query))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--source",
        choices=("http", "sql"),
        default="http",
        help="http (default): re-invoke chat via debug_trace; "
        "sql: read eval_traces.search_query for given run_ids.",
    )
    ap.add_argument("--old-backend", default=None)
    ap.add_argument("--new-backend", default=None)
    ap.add_argument(
        "--run-id-old",
        default=None,
        help="(sql mode) run_id of the OLD baseline run.",
    )
    ap.add_argument(
        "--run-id-new",
        default=None,
        help="(sql mode) run_id of the NEW baseline run.",
    )
    ap.add_argument("--dataset", required=False)
    ap.add_argument("--session-cookie-file", required=False)
    ap.add_argument("--me-json", required=False)
    ap.add_argument(
        "--filter-ids",
        default="",
        help="Comma-separated item ids; default = all items",
    )
    ap.add_argument(
        "--output",
        default="/tmp/prompt-fingerprint-diff.md",
        help="Markdown diff output path",
    )
    ap.add_argument(
        "--old-commit",
        default=None,
        help="Optional: prod commit hash for old backend (recorded in header)",
    )
    ap.add_argument(
        "--new-commit",
        default=None,
        help="Optional: prod commit hash for new backend (recorded in header)",
    )
    args = ap.parse_args()

    if args.source == "sql":
        if not (args.run_id_old and args.run_id_new):
            print(
                "[err] --source=sql requires --run-id-old and --run-id-new",
                file=sys.stderr,
            )
            return 2
        print(f"[sql] reading eval_traces for {args.run_id_old} vs {args.run_id_new}")
        old = asyncio.run(_load_from_sql(args.run_id_old))
        new = asyncio.run(_load_from_sql(args.run_id_new))
        old_label = f"run:{args.run_id_old}"
        new_label = f"run:{args.run_id_new}"
    else:
        if not (args.old_backend and args.new_backend
                and args.dataset and args.session_cookie_file and args.me_json):
            print(
                "[err] --source=http requires --old-backend / --new-backend / "
                "--dataset / --session-cookie-file / --me-json",
                file=sys.stderr,
            )
            return 2
        dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        show_id = dataset["show_id"]
        items = dataset.get("items") or []
        if args.filter_ids:
            ids = [s.strip() for s in args.filter_ids.split(",") if s.strip()]
            by_id = {i["id"]: i for i in items}
            items = [by_id[i] for i in ids if i in by_id]

        cookie_header, csrf_header = _read_cookie_csrf(
            Path(args.session_cookie_file), Path(args.me_json)
        )

        print(f"[old] {args.old_backend} ({len(items)} items)")
        old = _run_eval_for_backend(
            args.old_backend, items, show_id, cookie_header, csrf_header
        )
        print(f"[new] {args.new_backend} ({len(items)} items)")
        new = _run_eval_for_backend(
            args.new_backend, items, show_id, cookie_header, csrf_header
        )
        old_label = args.old_backend
        new_label = args.new_backend

    md = _render_diff_markdown(old, new, old_label, new_label)
    if args.old_commit or args.new_commit:
        header = (
            f"<!-- old_commit={args.old_commit or '?'} "
            f"new_commit={args.new_commit or '?'} -->\n"
        )
        md = header + md
    Path(args.output).write_text(md, encoding="utf-8")
    print(f"\n✓ wrote {args.output}")
    print(md.split("**Summary**:")[-1].strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
