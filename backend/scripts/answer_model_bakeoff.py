"""Answer-model bake-off harness (change: answer-model-bakeoff-and-switch).

Goal (design D1/D4): pick an answer-step model that HONORS forced `tool_choice`
with the full 14-tool spec, with good quality/cost. gpt-4o (current) silently
ignores forced tool_choice → b22's deterministic first-turn
`search_with_topic_prefilter` nudge is dormant in prod.

What it does, entirely via the PROD API (no direct prod DB creds needed — the
admin `PUT /admin/ai-steps/answer` mutates the same `ai_steps` row that the
design's raw `UPDATE` targets; `get_step_config` reads the row per-request so
the switch is live, no redeploy):

  1. e2e-login (admin) → session cookie + CSRF.
  2. GET /admin/ai-steps → snapshot the ORIGINAL answer config (model=gpt-4o).
  3. For each arm model: PUT answer.model=<arm>, then run the hard-coded subset
     through the full agentic pipeline (`?debug_trace=true`), capturing per item:
       first_tool, ep107_cited, prompt/completion tokens, cost, factual (judge),
       chunk_recall_grouped, full answer.
  4. finally: restore answer.model to the ORIGINAL value and verify (D5 safety).

Outputs (to OUT_DIR): a JSON record, a markdown summary table, and a side-by-side
answer dump for human review (D2 — Jacky picks; harness does not auto-select).

Run from repo root so `backend.eval.*` imports resolve:
    python -m backend.scripts.answer_model_bakeoff            # full bake-off (task 2.1)
    python -m backend.scripts.answer_model_bakeoff --dry-run  # 1 arm × 1 item (task 1.1 verify)

Auth: reads ~/.config/podcastrag/e2e-token (never printed). Judge key: OPENAI_API_KEY
(== AI Hub key, per repo memory) loaded from backend/.env.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load backend/.env so the judge (OPENAI_API_KEY == AI Hub key) is available.
_ENV_PATH = REPO_ROOT / "backend" / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from backend.eval.graders import chunk_recall_grouped  # noqa: E402
from backend.eval.judge_chat_v2 import build_payload, invoke_judge  # noqa: E402

# ─────────────────────────────────────────────────────────────────────
# Bake-off configuration (design D1 / D4 — hard-coded per task 1.1)
# ─────────────────────────────────────────────────────────────────────
API = "https://podcastrag-api.zeabur.app"
DATASET = REPO_ROOT / "backend" / "eval" / "datasets" / "extended-multi-turn-40.json"
EP107_ID = "8b3d4c1d-be8d-4dde-b12c-4cbe9b60ef21"  # b23 ground-truth episode
E2E_TOKEN_PATH = Path.home() / ".config" / "podcastrag" / "e2e-token"
OUT_DIR = REPO_ROOT / "backend" / "scripts" / "bakeoff_out"
CHANGE_DIR = REPO_ROOT / "openspec" / "changes" / "answer-model-bakeoff-and-switch"

# Candidate models (proposal — all pre-verified to honor forced tool_choice).
# gpt-4o is included as a quality/cost BASELINE arm (it ignores forced
# tool_choice — that is the whole reason for this change) so factual scores
# have a same-subset reference, per success criterion "不低於 gpt-4o baseline".
CANDIDATES = ["gpt-4.1", "gpt-5.1", "gemini-2.5-flash", "gemini-2.5-pro"]
BASELINE = "gpt-4o"
ARMS = [BASELINE] + CANDIDATES

# Hard-coded subset (all human-verified items; covers routing / fact /
# comprehension / refusal / multi-turn). b23 is the routing HARD GATE.
SUBSET_IDS = ["b23", "b20", "b11", "b14", "b15", "b27", "b29", "b33", "mt01"]

# AI Hub per-1M-token prices (USD), captured 2026-06-07 (design D4). gpt-4o is a
# best-effort baseline reference price (not a switch candidate).
PRICING = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-5.1": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gpt-4o": (2.50, 10.00),  # baseline reference only
}


# ─────────────────────────────────────────────────────────────────────
# HTTP — admin session via e2e backdoor + CSRF
# ─────────────────────────────────────────────────────────────────────
class ProdSession:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.csrf = ""

    def login(self) -> None:
        token = E2E_TOKEN_PATH.read_text(encoding="utf-8").strip()
        # Backdoor login: token only in URL, never logged.
        req = urllib.request.Request(f"{self.base}/auth/_e2e_login?token={token}")
        try:
            self.opener.open(req, timeout=20).read()
        except urllib.error.HTTPError as exc:
            # 302 redirect is success for the login GET.
            if exc.code not in (301, 302):
                raise
        me = json.loads(self.opener.open(f"{self.base}/me", timeout=20).read())
        if me.get("role") != "admin":
            raise RuntimeError(f"e2e session is not admin: {me.get('role')}")
        self.csrf = me.get("csrf_token", "") or ""
        if not self.csrf:
            raise RuntimeError("no csrf_token from /me")

    def _headers(self, state_changing: bool) -> dict:
        h = {"Content-Type": "application/json"}
        if state_changing:
            h["Origin"] = "https://app.podcastrag.app"
            h["X-CSRF-Token"] = self.csrf
        return h

    def _send(self, method: str, path: str, body: dict | None,
              state_changing: bool, timeout: float) -> dict:
        """Send a request; on HTTP 401 (session expired mid-run — the full
        bake-off outlives the e2e session TTL) re-login once and retry. CSRF +
        cookies refresh on re-login, so the retry carries fresh credentials."""
        for attempt in range(2):
            data = json.dumps(body).encode("utf-8") if body is not None else None
            req = urllib.request.Request(
                f"{self.base}{path}", data=data,
                headers=self._headers(state_changing), method=method,
            )
            try:
                return json.loads(self.opener.open(req, timeout=timeout).read().decode())
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    print("[bakeoff] session 401 — re-logging in", file=sys.stderr)
                    self.login()
                    continue
                raise

    def get(self, path: str, timeout: float = 30.0) -> dict:
        return self._send("GET", path, None, False, timeout)

    def put(self, path: str, body: dict, timeout: float = 30.0) -> dict:
        return self._send("PUT", path, body, True, timeout)

    def post(self, path: str, body: dict, timeout: float = 120.0) -> dict:
        return self._send("POST", path, body, True, timeout)


# ─────────────────────────────────────────────────────────────────────
# ai_steps.answer.model switching
# ─────────────────────────────────────────────────────────────────────
def get_answer_config(sess: ProdSession) -> dict:
    rows = sess.get("/admin/ai-steps")
    for r in rows:
        if r.get("step_key") == "answer":
            return r
    raise RuntimeError("no answer step in /admin/ai-steps")


def set_answer_model(sess: ProdSession, orig: dict, model: str) -> str:
    """PUT the answer step with a new model, keeping base_url/api_key/extra.
    Returns the model now live (verified via GET)."""
    body = {
        "base_url": orig["base_url"],
        "model": model,
        "api_key_id": orig["api_key_id"],
    }
    extra = orig.get("extra_config")
    if extra:
        body["extra_config"] = extra
    sess.put("/admin/ai-steps/answer", body)
    live = get_answer_config(sess).get("model")
    if live != model:
        raise RuntimeError(f"set_answer_model verify failed: wanted {model}, live {live}")
    return live


# ─────────────────────────────────────────────────────────────────────
# One agentic query (single or multi-turn) with debug_trace
# ─────────────────────────────────────────────────────────────────────
def _run_query(sess: ProdSession, show_id: str, question: str,
               messages: list, session_id: str) -> dict:
    body = {
        "mode": "chat",
        "question": question,
        "messages": messages,
        "session_id": session_id,
    }
    return sess.post(
        f"/shows/{show_id}/query?debug_trace=true", body, timeout=180.0
    )


def _tokens_from_trace(resp: dict) -> tuple[int, int]:
    trace = resp.get("trace") or {}
    calls = trace.get("llm_calls") or []
    pt = sum(int(c.get("prompt_tokens") or 0) for c in calls)
    ct = sum(int(c.get("completion_tokens") or 0) for c in calls)
    return pt, ct


def _first_tool(resp: dict) -> str | None:
    tcs = resp.get("tool_calls") or []
    return tcs[0].get("name") if tcs else None


def _ep107_cited(resp: dict) -> bool:
    for c in resp.get("citations") or []:
        if str(c.get("episode_id")) == EP107_ID:
            return True
    return False


def run_item(sess: ProdSession, show_id: str, item: dict) -> dict:
    """Run one dataset item end-to-end; return metrics dict.
    Multi-turn: replay turns with a shared session_id + growing messages.
    first_tool/ep107 captured from turn 0 (where the routing nudge fires);
    answer/factual scored on the LAST turn; tokens summed across turns."""
    sid = uuid.uuid4().hex
    sid_uuid = str(uuid.UUID(sid))
    is_mt = bool(item.get("is_multi_turn"))
    turns = item.get("turns") or [] if is_mt else [item]

    messages: list = []
    pt_total = ct_total = 0
    first_tool = None
    ep107 = False
    last_resp: dict = {}
    answers: list[str] = []
    err = None

    try:
        for ti, turn in enumerate(turns):
            q = turn.get("question") or item.get("question") or ""
            resp = _run_query(sess, show_id, q, messages, sid_uuid)
            pt, ct = _tokens_from_trace(resp)
            pt_total += pt
            ct_total += ct
            if ti == 0:
                first_tool = _first_tool(resp)
                ep107 = _ep107_cited(resp)
            else:
                ep107 = ep107 or _ep107_cited(resp)
            ans = resp.get("answer") or ""
            answers.append(ans)
            messages = messages + [
                {"role": "user", "content": q},
                {"role": "assistant", "content": ans},
            ]
            last_resp = resp
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
            json.JSONDecodeError, OSError) as exc:
        err = f"{type(exc).__name__}: {exc}"

    # chunk_recall_grouped (grader auto-scopes turns[0] for multi-turn)
    recall = None
    if last_resp:
        try:
            g = chunk_recall_grouped.grade(item, last_resp)
            recall = g.get("score") if g else None
        except Exception as exc:  # noqa: BLE001 — scoring must not abort the arm
            err = err or f"recall_err: {exc}"

    # factual judge on the LAST turn's scope
    factual = None
    if last_resp and not err:
        scope = turns[-1] if is_mt else item
        try:
            payload = build_payload(item, last_resp, turn_scope=scope)
            verdict = invoke_judge(payload)
            fc = (verdict or {}).get("factual_correctness") or {}
            factual = fc.get("score")
        except Exception as exc:  # noqa: BLE001
            err = err or f"judge_err: {exc}"

    return {
        "id": item["id"],
        "design_type": item.get("design_type"),
        "is_multi_turn": is_mt,
        "first_tool": first_tool,
        "ep107_cited": ep107,
        "prompt_tokens": pt_total,
        "completion_tokens": ct_total,
        "factual": factual,
        "chunk_recall": recall,
        "answer": "\n---\n".join(answers),
        "error": err,
        # cost filled in by caller (needs arm price)
    }


# ─────────────────────────────────────────────────────────────────────
# Main bake-off loop
# ─────────────────────────────────────────────────────────────────────
def _cost(model: str, pt: int, ct: int) -> float:
    pin, pout = PRICING.get(model, (0.0, 0.0))
    return round(pt / 1e6 * pin + ct / 1e6 * pout, 6)


def run_bakeoff(arms: list[str], subset_ids: list[str]) -> dict:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    show_id = data["show_id"]
    by_id = {it["id"]: it for it in data["items"]}
    subset = [by_id[i] for i in subset_ids if i in by_id]
    missing = [i for i in subset_ids if i not in by_id]
    if missing:
        raise RuntimeError(f"subset ids not in dataset: {missing}")

    sess = ProdSession(API)
    sess.login()
    orig = get_answer_config(sess)
    orig_model = orig["model"]
    print(f"[bakeoff] original answer.model = {orig_model}", file=sys.stderr)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cp_path = OUT_DIR / ".bakeoff-checkpoint.json"
    results: dict[str, list] = {}
    try:
        for arm in arms:
            # Proactive fresh login per arm so a long arm never outlives the
            # session; _send's 401-retry remains the safety net mid-arm.
            sess.login()
            live = set_answer_model(sess, orig, arm)
            print(f"[bakeoff] === arm {arm} (live={live}) ===", file=sys.stderr)
            # get_step_config reads ai_steps per-request; small settle margin.
            time.sleep(1.0)
            arm_rows = []
            for n, item in enumerate(subset, 1):
                print(f"[bakeoff]   [{n}/{len(subset)}] {item['id']}…", file=sys.stderr)
                rec = run_item(sess, show_id, item)
                rec["model"] = arm
                rec["cost"] = _cost(arm, rec["prompt_tokens"], rec["completion_tokens"])
                if rec["error"]:
                    print(f"[bakeoff]     ! error: {rec['error']}", file=sys.stderr)
                arm_rows.append(rec)
            results[arm] = arm_rows
            # Per-arm checkpoint: a crash on a later arm still preserves
            # completed arms (the original run lost 4 arms by only writing at
            # the very end).
            tmp = cp_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cp_path)
            print(f"[bakeoff]   checkpoint saved ({len(results)} arms)", file=sys.stderr)
    finally:
        # The session that died is WHY we may be in finally; force a fresh
        # login before restoring so the restore PUT cannot 401 (the bug that
        # left prod on a non-baseline model the first time).
        try:
            sess.login()
        except Exception as exc:  # noqa: BLE001
            print(f"[bakeoff] !!! re-login before restore failed: {exc}", file=sys.stderr)
        restored = set_answer_model(sess, orig, orig_model)
        print(f"[bakeoff] restored answer.model = {restored}", file=sys.stderr)
        if restored != orig_model:
            print("[bakeoff] !!! RESTORE MISMATCH — CHECK PROD ai_steps !!!",
                  file=sys.stderr)

    if cp_path.exists():
        cp_path.unlink()
    return {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "show_id": show_id,
        "dataset": str(DATASET.relative_to(REPO_ROOT)),
        "original_model": orig_model,
        "arms": arms,
        "subset_ids": subset_ids,
        "pricing_usd_per_1m": PRICING,
        "results": results,
    }


def _arm_totals(rows: list) -> dict:
    facts = [r["factual"] for r in rows if isinstance(r.get("factual"), (int, float))]
    recs = [r["chunk_recall"] for r in rows if isinstance(r.get("chunk_recall"), (int, float))]
    return {
        "total_cost": round(sum(r.get("cost") or 0 for r in rows), 6),
        "factual_mean": round(mean(facts), 3) if facts else None,
        "chunk_recall_mean": round(mean(recs), 3) if recs else None,
        "errors": sum(1 for r in rows if r.get("error")),
    }


def write_outputs(report: dict) -> tuple[Path, Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = report["run_at_utc"].replace(":", "").replace("-", "")[:15]
    json_path = OUT_DIR / f"bakeoff-{stamp}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Summary table
    lines = [
        f"# Answer-model bake-off — {report['run_at_utc']}",
        "",
        f"- subset: {', '.join(report['subset_ids'])} (all human-verified)",
        f"- original answer.model: `{report['original_model']}` (restored after run)",
        f"- b23 routing HARD GATE: first tool == `search_with_topic_prefilter` + EP107 cited",
        "",
        "## Per-arm summary",
        "",
        "| model | total cost (USD) | factual mean | chunk_recall mean | b23 first_tool | b23 EP107 | errors |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in report["arms"]:
        rows = report["results"].get(arm, [])
        t = _arm_totals(rows)
        b23 = next((r for r in rows if r["id"] == "b23"), {})
        gate = b23.get("first_tool") or "—"
        ep = "✓" if b23.get("ep107_cited") else "✗"
        note = " (baseline)" if arm == report["original_model"] else ""
        lines.append(
            f"| {arm}{note} | {t['total_cost']} | {t['factual_mean']} | "
            f"{t['chunk_recall_mean']} | `{gate}` | {ep} | {t['errors']} |"
        )

    lines += ["", "## Per-item × arm detail", ""]
    lines.append("| id | type | " + " | ".join(report["arms"]) + " |")
    lines.append("|---|---|" + "|".join(["---"] * len(report["arms"])) + "|")
    ids = report["subset_ids"]
    for iid in ids:
        cells = []
        dtype = ""
        for arm in report["arms"]:
            r = next((x for x in report["results"].get(arm, []) if x["id"] == iid), {})
            dtype = r.get("design_type") or dtype
            ft = (r.get("first_tool") or "—").replace("search_with_topic_prefilter", "prefilter")
            cells.append(f"f={r.get('factual')} r={r.get('chunk_recall')} {ft}")
        lines.append(f"| {iid} | {dtype} | " + " | ".join(cells) + " |")

    md_path = OUT_DIR / f"bakeoff-{stamp}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Side-by-side answer dump
    sbs = [f"# Side-by-side answers — {report['run_at_utc']}", ""]
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in data["items"]}
    for iid in ids:
        item = by_id.get(iid, {})
        q = item.get("question") or (item.get("turns", [{}])[0].get("question") if item.get("turns") else "")
        sbs += [f"## {iid} ({item.get('design_type')}) — {q}", ""]
        exp = item.get("expected_answer_summary") or ""
        if exp:
            sbs += [f"**expected**: {exp}", ""]
        for arm in report["arms"]:
            r = next((x for x in report["results"].get(arm, []) if x["id"] == iid), {})
            sbs += [
                f"### {arm}  (factual={r.get('factual')}, recall={r.get('chunk_recall')}, "
                f"first_tool={r.get('first_tool')}, ep107={r.get('ep107_cited')})",
                "",
                (r.get("answer") or "(no answer)"),
                "",
            ]
    sbs_path = OUT_DIR / f"bakeoff-{stamp}-answers.md"
    sbs_path.write_text("\n".join(sbs) + "\n", encoding="utf-8")

    # Copy summary + answers into the change dir for retention.
    CHANGE_DIR.mkdir(parents=True, exist_ok=True)
    (CHANGE_DIR / "bakeoff-results.md").write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    (CHANGE_DIR / "bakeoff-answers.md").write_text(sbs_path.read_text(encoding="utf-8"), encoding="utf-8")
    return json_path, md_path, sbs_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="1 arm (gpt-4.1) × 1 item (b23) to verify the field dict + restore.")
    args = ap.parse_args(argv)

    if args.dry_run:
        arms = ["gpt-4.1"]
        subset = ["b23"]
    else:
        arms = ARMS
        subset = SUBSET_IDS

    report = run_bakeoff(arms, subset)
    json_path, md_path, sbs_path = write_outputs(report)
    print(f"\n[ok] json:    {json_path}", file=sys.stderr)
    print(f"[ok] summary: {md_path}", file=sys.stderr)
    print(f"[ok] answers: {sbs_path}", file=sys.stderr)
    # Echo the summary table to stdout for quick read.
    print(md_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
