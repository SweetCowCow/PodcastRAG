"""Dogfood trace dump for agent-trace-telemetry investigation.

Replays the 30-question `this-not-that-cool.json` golden set against prod
`/query?debug_trace=true` with an admin session cookie and writes every
response (including full agent telemetry trace) to
`.tmp/dogfood_trace_2026-05-22.json` for offline analysis.

Per spec `dogfood_trace_dump script captures 30-question trace for offline
analysis`:
  - admin session cookie loaded from `~/.config/podcastrag/playwright-state.json`
  - retry once on HTTP 5xx or timeout, record `{"id": qid, "error": "<msg>"}`
    on double-fail so the dump remains complete (30 entries always)
  - output goes to `.tmp/` (gitignored per `feedback_case_studies_no_commit.md`)

Usage:
  python3 backend/scripts/dogfood_trace_dump.py \\
    [--dataset backend/eval/datasets/this-not-that-cool.json] \\
    [--backend-url https://podcastrag-api.zeabur.app] \\
    [--origin https://app.podcastrag.app] \\
    [--out .tmp/dogfood_trace_2026-05-22.json]

Secrets policy (per `feedback_subprocess_creds_via_env.md`): session_id is
read from playwright-state.json on disk, NEVER passed via argv.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "backend/eval/datasets/this-not-that-cool.json"
DEFAULT_OUT = REPO_ROOT / ".tmp/dogfood_trace_2026-05-22.json"
DEFAULT_BACKEND = "https://podcastrag-api.zeabur.app"
DEFAULT_ORIGIN = "https://app.podcastrag.app"
PLAYWRIGHT_STATE = Path.home() / ".config/podcastrag/playwright-state.json"
REQUEST_TIMEOUT_S = 120.0


def _load_session_cookie() -> str:
    """Load session_id from playwright-state.json (no argv passing)."""
    if not PLAYWRIGHT_STATE.exists():
        sys.exit(f"playwright-state.json not found at {PLAYWRIGHT_STATE}")
    state = json.loads(PLAYWRIGHT_STATE.read_text())
    for c in state.get("cookies", []):
        if c.get("name") == "session_id":
            return c["value"]
    sys.exit("session_id cookie not found in playwright-state.json")


def _fetch_csrf(backend_url: str, token: str) -> str:
    req = urllib.request.Request(
        f"{backend_url}/me", headers={"Cookie": f"session_id={token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return json.loads(resp.read().decode()).get("csrf_token", "") or ""
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        sys.exit(f"failed to fetch /me CSRF: {exc}")


def _post_query(
    backend_url: str,
    show_id: str,
    question: str,
    session_token: str,
    csrf_token: str,
    origin: str,
) -> dict:
    url = f"{backend_url}/shows/{show_id}/query?debug_trace=true"
    headers = {
        "Content-Type": "application/json",
        "Cookie": f"session_id={session_token}",
        "X-CSRF-Token": csrf_token,
        "Origin": origin,
    }
    body = json.dumps(
        {"question": question, "mode": "chat", "messages": []}
    ).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode())


def _post_with_retry(
    backend_url: str,
    show_id: str,
    question: str,
    session_token: str,
    csrf_token: str,
    origin: str,
) -> tuple[dict | None, str | None]:
    """Return (response_body, None) on success, (None, error_msg) on double-fail.

    Retries once on HTTP 5xx, urlopen errors, or socket timeouts. 4xx errors
    are returned as failure without retry (auth / CSRF problems won't
    self-heal on retry).
    """
    last_err = ""
    for attempt in (1, 2):
        try:
            return _post_query(
                backend_url, show_id, question, session_token, csrf_token, origin
            ), None
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}: {exc.reason}"
            if exc.code < 500:
                return None, last_err  # no retry for 4xx
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        except json.JSONDecodeError as exc:
            last_err = f"JSON decode error: {exc}"
        if attempt == 1:
            time.sleep(2.0)
    return None, last_err


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    p.add_argument("--backend-url", default=DEFAULT_BACKEND)
    p.add_argument("--origin", default=DEFAULT_ORIGIN)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    dataset = json.loads(args.dataset.read_text())
    show_id = dataset["show_id"]
    items = dataset["items"]
    print(f"Dogfood trace dump: {len(items)} questions for show {show_id}")
    print(f"  backend : {args.backend_url}")
    print(f"  origin  : {args.origin}")
    print(f"  output  : {args.out}")

    session_token = _load_session_cookie()
    csrf_token = _fetch_csrf(args.backend_url, session_token)
    if not csrf_token:
        sys.exit("empty CSRF token from /me — session may be expired")

    entries: list[dict] = []
    n_success = 0
    n_error = 0
    t_total_start = time.perf_counter()

    for idx, item in enumerate(items, 1):
        qid = item["id"]
        question = item["question"]
        print(f"  [{idx:>2}/{len(items)}] {qid} ...", end=" ", flush=True)
        t0 = time.perf_counter()
        resp, err = _post_with_retry(
            args.backend_url,
            show_id,
            question,
            session_token,
            csrf_token,
            args.origin,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if resp is not None:
            n_success += 1
            entries.append(
                {
                    "id": qid,
                    "question": question,
                    "elapsed_ms": elapsed_ms,
                    "answer": resp.get("answer"),
                    "tool_calls": resp.get("tool_calls"),
                    "agent_truncated": resp.get("agent_truncated"),
                    "trace": resp.get("trace"),
                }
            )
            print(f"OK ({elapsed_ms:.0f}ms)")
        else:
            n_error += 1
            entries.append({"id": qid, "question": question, "error": err})
            print(f"ERROR ({err})")

    total_s = time.perf_counter() - t_total_start
    args.out.write_text(json.dumps(entries, ensure_ascii=False, indent=2))

    print()
    print(f"Done in {total_s:.1f}s")
    print(f"  n_success : {n_success}")
    print(f"  n_error   : {n_error}")
    print(f"  total     : {len(entries)}")
    print(f"  written   : {args.out}")


if __name__ == "__main__":
    main()
