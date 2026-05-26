"""Driver for `POST /admin/diagnose/prefilter-rank`.

Per change retrieval-cross-episode-chunk-recovery task 1.1. Reads e2e session
cookies (same pattern as run_chat_agent_eval_v2), hits the admin endpoint,
saves the response JSON, and prints a human-readable rank table.

Usage:
    python -m backend.scripts.diagnose_prefilter_rank \\
        --mini-set-ids b20,b21,b23 \\
        --top-n 100 \\
        --output /tmp/diagnose-prefilter-rank.json \\
        --backend https://podcastrag-api.zeabur.app \\
        --session-cookie-file /tmp/podcastrag_session.txt \\
        --me-json /tmp/me_resp.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _read_cookies_and_csrf(cookie_file: Path, me_json: Path) -> tuple[str, str]:
    parts: list[str] = []
    for line in cookie_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("#HttpOnly_"):
            fields = line[len("#HttpOnly_"):].split("\t")
        elif line.startswith("#") or not line:
            continue
        else:
            fields = line.split("\t")
        if len(fields) >= 7:
            parts.append(f"{fields[5]}={fields[6]}")
    cookie_header = "; ".join(parts)
    csrf = json.loads(me_json.read_text(encoding="utf-8"))["csrf_token"]
    return cookie_header, csrf


def _post(backend: str, body: dict, cookie: str, csrf: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{backend}/admin/diagnose/prefilter-rank",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Cookie": cookie,
            "X-CSRF-Token": csrf,
            "Origin": "https://app.podcastrag.app",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:500]
        print(f"HTTP {e.code}: {body_txt}", file=sys.stderr)
        raise


def _print_table(payload: dict) -> None:
    items = payload.get("items", [])
    for it in items:
        iid = it.get("item_id")
        if "error" in it:
            print(f"\n=== {iid}: ERROR — {it['error']} ===")
            continue
        print(f"\n=== {iid} (top_n={it['top_n']}, prefilter_eps={it['prefilter_episode_count']}) ===")
        print(f"question: {it['question']}")
        print(f"gt_total: {it['gt_total']}, retrieved_count: {it['retrieved_count']}")
        print("bucket counts:", it["bucket_counts"])
        print(f"{'rank':<6} {'cutoff':<10} {'kind':<6} chunk_id")
        for gr in it["gt_ranks"]:
            rank_str = str(gr["rank"]) if gr["rank"] is not None else "—"
            print(f"{rank_str:<6} {gr['cutoff_in']:<10} {gr['kind']:<6} {gr['gt_chunk_id']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mini-set-ids", default="b20,b21,b23")
    ap.add_argument("--top-n", type=int, default=100)
    ap.add_argument("--output", default="/tmp/diagnose-prefilter-rank.json")
    ap.add_argument("--backend", default="https://podcastrag-api.zeabur.app")
    ap.add_argument("--session-cookie-file", default="/tmp/podcastrag_session.txt")
    ap.add_argument("--me-json", default="/tmp/me_resp.json")
    args = ap.parse_args()

    cookie, csrf = _read_cookies_and_csrf(Path(args.session_cookie_file), Path(args.me_json))
    body = {
        "mini_set_ids": [s.strip() for s in args.mini_set_ids.split(",") if s.strip()],
        "top_n": args.top_n,
    }
    resp = _post(args.backend, body, cookie, csrf)
    out_path = Path(args.output)
    out_path.write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    _print_table(resp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
