#!/usr/bin/env python3
"""Stage 1 of L3 ground-truth audit: pull search top-K + kw_hit, emit a
markdown review report for a batch of turns from extended-multi-turn-40.

Usage:
    AUTH_TOKEN=<session> python3 backend/eval/scripts/gt_audit_export.py \\
        --batch A \\
        --out /tmp/gt_audit_batch_a.md

Batches:
    A = 12 new single-turn (b02 b03 b04 b06 b07 b10 b11 b12 b13 b24 b25 b26)
    B = 5 source-id-mismatch existing (b05 b14 b20 b21 b22)
    C = 4 multi-turn t1 (mt01 mt02 mt03 mt04, turn 1 only)

Per turn the report shows up to 8 candidate chunks with:
    keep | chunk_id | episode title | mm:ss | rrf | kw_hit | text head
Plus question / expected_keywords / design_type / a transcript URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

DATASET = Path("backend/eval/datasets/extended-multi-turn-40.json")
BACKEND = "https://podcastrag-api.zeabur.app"
FRONTEND = "https://app.podcastrag.app"
TOP_K = 8
TEXT_HEAD_CHARS = 80

BATCHES: dict[str, list[str]] = {
    "A": ["b02","b03","b04","b06","b07","b10","b11","b12","b13","b24","b25","b26"],
    "B": ["b05","b14","b20","b21","b22"],
    "C": ["mt01","mt02","mt03","mt04"],
}


def _fetch_csrf(token: str) -> str:
    req = urllib.request.Request(f"{BACKEND}/me", headers={"Cookie": f"session_id={token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode()).get("csrf_token", "")


def _search_dual(
    show_id: str,
    question: str,
    keywords: list[str],
    design_type: str,
    token: str,
    csrf: str,
) -> list[dict]:
    """Two-pass search and merge:
    (1) original question  (2) joined keywords as a supplemental query.
    Trigger condition: expected_keywords non-empty (covers any chunk-level
    scorable type regardless of declared design_type — b05 standalone shows
    a `guest_find` row whose expected_keywords are deep_dive-style).
    Dedupe by (episode_id, start_time)."""
    base = _search(show_id, question, token, csrf)
    if not keywords:
        return base
    kw_query = " ".join(keywords)
    supp = _search(show_id, kw_query, token, csrf)
    # tag each hit with the source query so the report can show provenance
    for r in base:
        r["_via"] = "q"
    for r in supp:
        r["_via"] = "kw"
    seen: set[tuple[str, float]] = set()
    merged: list[dict] = []
    for r in base + supp:
        key = (r["episode_id"], float(r.get("start_time", 0.0) or 0.0))
        if key in seen:
            continue
        seen.add(key)
        merged.append(r)
    return merged


def _search(show_id: str, question: str, token: str, csrf: str) -> list[dict]:
    body = json.dumps({"question": question, "k": TOP_K}).encode()
    req = urllib.request.Request(
        f"{BACKEND}/shows/{show_id}/search",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Cookie": f"session_id={token}",
            "X-CSRF-Token": csrf,
            "Origin": FRONTEND,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode())
        return resp.get("results", [])
    except urllib.error.URLError as e:
        print(f"  [warn] search failed: {e}", file=sys.stderr)
        return []


def _kw_hit(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    text_l = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in text_l)
    return round(hits / len(keywords), 2)


def _mmss(sec: float) -> str:
    s = int(sec)
    return f"{s // 60:02d}:{s % 60:02d}"


def _chunk_id_canonical(episode_id: str, start_time: float) -> str:
    return f"ep:{episode_id}@{float(start_time):.2f}"


def _suggest_keep(rrf: float, kw_hit: float) -> str:
    # default checkbox state: rrf ≥ 0.7 OR kw_hit ≥ 0.4 → [x], else [ ]
    return "[x]" if (rrf >= 0.7 or kw_hit >= 0.4) else "[ ]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", choices=list(BATCHES))
    ap.add_argument("--items", help="comma-separated item ids, overrides --batch")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    token = os.environ.get("AUTH_TOKEN", "")
    if not token:
        sys.exit("AUTH_TOKEN env required (refresh via backdoor first)")
    csrf = _fetch_csrf(token)

    dataset = json.loads(DATASET.read_text())
    show_id = dataset["show_id"]
    items_by_id = {it["id"]: it for it in dataset["items"]}

    if args.items:
        ids = [s.strip() for s in args.items.split(",") if s.strip()]
        batch_label = ",".join(ids)
    elif args.batch:
        ids = BATCHES[args.batch]
        batch_label = args.batch
    else:
        sys.exit("either --batch or --items required")

    out_lines: list[str] = []
    out_lines.append(f"# Ground-Truth Audit — {batch_label}\n")
    out_lines.append(
        "Edit `[x]` / `[ ]` per row. Default suggestion: keep if rrf≥0.7 OR kw_hit≥0.4. "
        "When done, run `gt_audit_import.py --in <this-file>` to write back.\n"
    )

    for item_id in ids:
        item = items_by_id.get(item_id)
        if not item:
            out_lines.append(f"\n## ⚠️ {item_id} not found in dataset\n")
            continue
        turns_to_audit = [(1, item["turns"][0])] if not item.get("is_multi_turn") else [(1, item["turns"][0])]
        # Batch C: multi-turn t1 only
        for turn_idx, turn in turns_to_audit:
            q = turn["question"]
            kws = turn.get("expected_answer_keywords", [])
            dtype = item.get("design_type", "?")
            src = item.get("source", "?")

            print(f"  searching {item_id} t{turn_idx}: {q[:50]}...", file=sys.stderr)
            hits = _search_dual(show_id, q, kws, dtype, token, csrf)

            out_lines.append(f"\n---\n\n## {item_id} t{turn_idx}  ({dtype}, source: {src})\n")
            out_lines.append(f"**question**：{q}\n\n")
            out_lines.append(f"**expected_keywords**：{', '.join(kws) if kws else '(none)'}\n\n")
            out_lines.append("| keep | chunk_id | episode | mm:ss | via | kw_hit | text head |\n")
            out_lines.append("|---|---|---|---|---|---|---|\n")
            for h in hits:
                text_head = (h.get("text", "") or "").replace("\n", " ").strip()
                text_head = text_head[:TEXT_HEAD_CHARS] + ("…" if len(text_head) > TEXT_HEAD_CHARS else "")
                ep_title = (h.get("episode_title", "") or "")[:40]
                start = float(h.get("start_time", 0.0) or 0.0)
                # backend search response uses field "distance" for rrf-equivalent ordering;
                # try common keys then fall back to "score"
                via = h.get("_via", "q")
                kw = _kw_hit(h.get("text", "") or "", kws)
                cid = _chunk_id_canonical(h["episode_id"], start)
                # default suggestion: hit via kw query OR kw_hit >= 0.4
                keep = "[x]" if (via == "kw" or kw >= 0.4) else "[ ]"
                src = (h.get("source") or "?")[:5]
                out_lines.append(
                    f"| {keep} | `{cid}` | {ep_title} ({src}) | {_mmss(start)} | {via} | {kw:.2f} | {text_head} |\n"
                )
            transcript_url = f"{FRONTEND}/transcript/{hits[0]['episode_id']}" if hits else ""
            if transcript_url:
                out_lines.append(f"\n🔗 first-hit episode transcript: {transcript_url}\n")
            out_lines.append("\n**note**：\n")

    Path(args.out).write_text("".join(out_lines))
    print(f"\nWritten: {args.out}")


if __name__ == "__main__":
    main()
