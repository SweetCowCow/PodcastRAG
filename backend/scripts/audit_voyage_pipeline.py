"""Stage A pipeline I/O audit for the voyage-rerank-tune-b22-b23 change.

For each dataset item, walk the chat-agent retrieval pipeline and dump a
per-stage (expected / actual / verdict) table so root cause can be confirmed
*before* any application-code fix.

Why audit instead of trust: a prior change shipped a latent citation-collector
bug that every unit test + debug_trace inspection missed; only the eval grader
(must_hits=0) exposed it. This script brackets each pipeline stage's I/O against
its expected shape so a silent drift can't hide behind a green-looking metric.

Data-source note (option A, 2026-06-04): the prod query trace does NOT expose
Voyage internals (the pre-rerank input pool chunks, the raw response
index/relevance_score pairs, or the index->chunks mapping) — those live inside
`voyage_rerank()` which only returns `(chunks_top_k, applied)`. To honour the
Stage-A "no application code" rule we treat Voyage as a black box: stage 5 is
observed via `rerank_input_count` + `rerank_applied`; stages 6-7 are reported
`unknown`; root cause is discriminated by bracketing stage 4 (is GT in the
retrieve_hybrid top-30 pool?) against stage 8 (did GT survive into
response.citations?), plus `fallback_to_full_pool` (did the request even enter
the prefilter+voyage path?).

Usage:
    python -m backend.scripts.audit_voyage_pipeline \\
        --item-ids b21,b22,b23 \\
        --backend https://podcastrag-api.zeabur.app \\
        --out /tmp/voyage-audit.json \\
        --session-cookie-file /tmp/podcastrag_session.txt \\
        --me-json /tmp/me_resp.json

Writes `<out>` (JSON) and `<out>.md` (markdown tables), and prints the tables
to stdout. Network failure on any single stage degrades that stage to
verdict=unknown / actual=None rather than crashing the run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# chunk_id format shared with the chunk_recall grader / diagnose_prefilter.
_CHUNK_RE = re.compile(r"^ep:([0-9a-f-]+)@(\d+\.\d+)$")
_MATCH_WINDOW_S = 10.0  # grader matches GT by (episode_id, start_time) +/- 10s
_PREFILTER_POOL_TOP_N = 30  # mirrors _PREFILTER_RERANK_TOP_N (retrieve_hybrid pool)

DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "eval"
    / "datasets"
    / "extended-multi-turn-40.json"
)
DEFAULT_SHOW_ID = "45fc2462-17cf-42f5-98a7-68fe1a222228"
_PREFILTER_TOOL = "search_with_topic_prefilter"
_TOPIC_FINDER_TOOL = "find_episodes_by_topic"


# --------------------------------------------------------------------------- #
# Session / HTTP helpers (reuse diagnose_prefilter_rank + run_chat_agent_eval) #
# --------------------------------------------------------------------------- #
def _read_session_and_csrf(cookie_file: Path, me_json: Path) -> tuple[str, str]:
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


def _request(
    method: str,
    url: str,
    cookie: str,
    csrf: str,
    body: dict | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    headers = {
        "Cookie": cookie,
        "X-CSRF-Token": csrf,
        "Origin": "https://app.podcastrag.app",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _preflight_me(backend: str, cookie: str, csrf: str) -> None:
    """Fail fast with a clear message when the session is stale."""
    try:
        me = _request("GET", f"{backend}/me", cookie, csrf, timeout=30.0)
    except urllib.error.HTTPError as e:
        print(
            f"FATAL: GET /me -> HTTP {e.code}. Session likely expired — refresh "
            f"the e2e cookie file before rerunning.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if me.get("role") != "admin":
        print(
            f"FATAL: /me role is {me.get('role')!r}, not admin. debug_trace is "
            f"silently ignored for non-admin sessions, so stages 2/3/5 would be "
            f"empty. Use an admin e2e session.",
            file=sys.stderr,
        )
        raise SystemExit(2)


# --------------------------------------------------------------------------- #
# Chunk-id parsing / matching                                                 #
# --------------------------------------------------------------------------- #
def _parse_chunk_id(cid: str) -> tuple[str, float] | None:
    m = _CHUNK_RE.match(cid)
    return (m.group(1), float(m.group(2))) if m else None


def _derive_episode_uuids(gt_chunk_ids: list[str]) -> list[str]:
    """Unique episode UUIDs implied by the GT chunk list (dataset's own
    expected_episode_uuids_* fields are mostly null)."""
    seen: list[str] = []
    for cid in gt_chunk_ids:
        parsed = _parse_chunk_id(cid)
        if parsed and parsed[0] not in seen:
            seen.append(parsed[0])
    return seen


def _chunk_matches_gt(ep_id: str, start_time: float, gt_chunk_ids: list[str]) -> str | None:
    """Return the GT chunk_id matched by (episode_id, start_time +/- window), else None."""
    for cid in gt_chunk_ids:
        parsed = _parse_chunk_id(cid)
        if not parsed:
            continue
        ep_gt, st_gt = parsed
        if ep_id == ep_gt and abs(start_time - st_gt) <= _MATCH_WINDOW_S:
            return cid
    return None


# --------------------------------------------------------------------------- #
# Dataset                                                                      #
# --------------------------------------------------------------------------- #
def _load_dataset() -> tuple[dict[str, dict], str]:
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    items = {i["id"]: i for i in data.get("items", [])}
    show_id = data.get("show_id") or DEFAULT_SHOW_ID
    return items, show_id


def _item_scope(item: dict) -> dict:
    """Single-turn items use the item; multi-turn use the first turn."""
    if item.get("is_multi_turn"):
        turns = item.get("turns") or []
        return turns[0] if turns else item
    return item


def _gt_chunks(scope: dict, item: dict) -> dict[str, list[str]]:
    def pick(key: str) -> list[str]:
        return scope.get(key) or item.get(key) or []

    must = pick("ground_truth_chunk_ids_must")
    either = pick("ground_truth_chunk_ids_either")
    acceptable = pick("ground_truth_chunk_ids_acceptable")
    return {
        "must": must,
        "either": either,
        "acceptable": acceptable,
        "primary": list(must) + list(either),  # what retrieval is graded against
    }


# --------------------------------------------------------------------------- #
# Per-stage extraction                                                         #
# --------------------------------------------------------------------------- #
def _stage(n: int, name: str, expected: Any, actual: Any, verdict: str) -> dict:
    return {"stage": n, "name": name, "expected": expected, "actual": actual, "verdict": verdict}


def _find_tool_calls(trace_resp: dict, name: str) -> list[dict]:
    return [tc for tc in (trace_resp.get("tool_calls") or []) if tc.get("name") == name]


def _decode_result_full(tc: dict) -> dict | None:
    raw = tc.get("result_full")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except (ValueError, TypeError):
        return None


def _audit_item(
    item_id: str,
    item: dict,
    *,
    backend: str,
    show_id: str,
    cookie: str,
    csrf: str,
) -> dict:
    scope = _item_scope(item)
    question = scope.get("question") or item.get("question")
    gt = _gt_chunks(scope, item)
    expected_eps = _derive_episode_uuids(gt["primary"])

    stages: list[dict] = []

    # --- Stage 1: dataset GT (control input) -------------------------------- #
    stage1_actual = {
        "question": question,
        "gt_must": gt["must"],
        "gt_either": gt["either"],
        "gt_acceptable": gt["acceptable"],
        "expected_episode_uuids": expected_eps,
    }
    stages.append(_stage(
        1, "dataset GT (control)",
        "non-empty question + >=1 GT chunk + >=1 expected episode",
        stage1_actual,
        "match" if (question and gt["primary"] and expected_eps) else "unknown",
    ))

    # --- Query the agent (trace) -------------------------------------------- #
    trace_resp: dict | None = None
    query_err: str | None = None
    try:
        trace_resp = _request(
            "POST",
            f"{backend}/shows/{show_id}/query?debug_trace=true",
            cookie,
            csrf,
            body={"question": question, "mode": "chat", "messages": []},
            timeout=180.0,
        )
    except (urllib.error.URLError, OSError, ValueError) as exc:
        query_err = f"{exc.__class__.__name__}: {exc}"

    prefilter_calls = _find_tool_calls(trace_resp, _PREFILTER_TOOL) if trace_resp else []
    prefilter_full = _decode_result_full(prefilter_calls[0]) if prefilter_calls else None
    topic_finder_calls = _find_tool_calls(trace_resp, _TOPIC_FINDER_TOOL) if trace_resp else []

    # --- Stage 2: agent topic extraction ------------------------------------ #
    if query_err:
        stages.append(_stage(2, "agent topic extraction", "topic relevant to question", None,
                             "unknown"))
    elif prefilter_calls:
        topics = [tc.get("args", {}).get("topic") for tc in prefilter_calls]
        queries = [tc.get("args", {}).get("query") for tc in prefilter_calls]
        stages.append(_stage(
            2, "agent topic extraction",
            f"{_PREFILTER_TOOL} called with a topic relevant to the question",
            {"topics": topics, "queries": queries},
            "match" if any(topics) else "drift",
        ))
    else:
        # Agent never invoked the topic-prefilter tool -> different route.
        invoked = sorted({tc.get("name") for tc in (trace_resp.get("tool_calls") or [])})
        stages.append(_stage(
            2, "agent topic extraction",
            f"{_PREFILTER_TOOL} invoked",
            {"prefilter_invoked": False, "tools_invoked": invoked},
            "drift",
        ))

    # --- Stage 3: find_episodes_by_topic candidate set ---------------------- #
    if query_err:
        stages.append(_stage(3, "find_episodes_by_topic output", "GT episodes in candidates",
                             None, "unknown"))
    elif prefilter_full is not None:
        # result_full exposes counts/source/fallback but not candidate UUIDs;
        # use output-chunk episodes + topic-finder enumeration (if any) as proxy.
        out_eps = sorted({c.get("episode_id") for c in (prefilter_full.get("chunks") or [])})
        finder_eps: list[str] = []
        for tc in topic_finder_calls:
            payload = _decode_result_full(tc)
            if payload:
                finder_eps.extend(str(e.get("episode_id")) for e in (payload.get("episodes") or []))
        gt_eps_in_output = [e for e in expected_eps if e in out_eps]
        gt_eps_in_finder = [e for e in expected_eps if e in finder_eps]
        covered = set(gt_eps_in_output) | set(gt_eps_in_finder)
        actual3 = {
            "prefilter_episode_count": prefilter_full.get("prefilter_episode_count"),
            "prefilter_source": prefilter_full.get("prefilter_source"),
            "fallback_to_full_pool": prefilter_full.get("fallback_to_full_pool"),
            "output_chunk_episodes": out_eps,
            "topic_finder_episodes": sorted(set(finder_eps)) or None,
            "expected_episode_uuids": expected_eps,
            "gt_episodes_observed": sorted(covered),
        }
        if prefilter_full.get("fallback_to_full_pool"):
            verdict3 = "drift"  # topic matched no episode -> no prefilter
        elif expected_eps and covered == set(expected_eps):
            verdict3 = "match"
        elif covered:
            verdict3 = "partial"
        else:
            # Candidate UUIDs not directly observable and no GT episode surfaced
            # downstream -> can't confirm membership from prod trace.
            verdict3 = "unknown"
        stages.append(_stage(
            3, "find_episodes_by_topic output",
            "all GT episodes present in topic-prefilter candidate set",
            actual3, verdict3,
        ))
    else:
        stages.append(_stage(
            3, "find_episodes_by_topic output",
            "all GT episodes present in candidate set",
            {"reason": "no search_with_topic_prefilter result_full in trace"},
            "unknown",
        ))

    # --- Stage 4: retrieve_hybrid top-30 pool (admin endpoint) -------------- #
    pf_item: dict | None = None
    try:
        pf_resp = _request(
            "POST",
            f"{backend}/admin/diagnose/prefilter-rank",
            cookie,
            csrf,
            body={"items": [item_id], "top_n": _PREFILTER_POOL_TOP_N, "show_id": show_id},
            timeout=180.0,
        )
        pf_item = next((x for x in pf_resp.get("items", []) if x.get("item_id") == item_id), None)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        pf_item = {"error": f"{exc.__class__.__name__}: {exc}"}

    if pf_item and "error" not in pf_item:
        gt_ranks = pf_item.get("gt_ranks", [])
        in_pool = [g for g in gt_ranks if g.get("rank") is not None]
        actual4 = {
            "top_n": pf_item.get("top_n"),
            "prefilter_episode_count": pf_item.get("prefilter_episode_count"),
            "bucket_counts": pf_item.get("bucket_counts"),
            "gt_ranks": [
                {"gt_chunk_id": g["gt_chunk_id"], "kind": g.get("kind"), "rank": g.get("rank")}
                for g in gt_ranks
            ],
            "gt_total": pf_item.get("gt_total"),
            "gt_in_pool": len(in_pool),
            "note": "ideal-prefilter pool: GT-episode-filtered retrieve_hybrid (isolates "
                    "within-episode ranking from topic-extraction noise)",
        }
        if gt_ranks and len(in_pool) == len(gt_ranks):
            verdict4 = "match"
        elif in_pool:
            verdict4 = "partial"
        else:
            verdict4 = "drift"  # GT absent from the top-30 pool -> retrieval miss
        stages.append(_stage(
            4, "retrieve_hybrid top-30 pool (GT rank)",
            f"all GT chunks rank <= {_PREFILTER_POOL_TOP_N}",
            actual4, verdict4,
        ))
    else:
        stages.append(_stage(
            4, "retrieve_hybrid top-30 pool (GT rank)",
            f"all GT chunks rank <= {_PREFILTER_POOL_TOP_N}",
            pf_item, "unknown",
        ))

    # --- Stage 5: voyage doc payload (count + applied; bytes not exposed) ---- #
    if prefilter_full is not None:
        applied = prefilter_full.get("rerank_applied")
        in_count = prefilter_full.get("rerank_input_count")
        actual5 = {
            "rerank_applied": applied,
            "rerank_input_count": in_count,
            "fallback_to_full_pool": prefilter_full.get("fallback_to_full_pool"),
            "doc_format": "text_only (chunk.text; rag_rerank.py:226)",
            "note": "actual doc bytes not exposed by prod trace",
        }
        if applied and in_count == _PREFILTER_POOL_TOP_N:
            verdict5 = "match"
        elif applied:
            verdict5 = "partial"  # applied but pool != expected N
        else:
            verdict5 = "drift"  # rerank not applied (fallback / no voyage key)
        stages.append(_stage(
            5, "voyage doc payload (count+applied)",
            f"rerank_applied=true, rerank_input_count={_PREFILTER_POOL_TOP_N}, text_only",
            actual5, verdict5,
        ))
    else:
        stages.append(_stage(
            5, "voyage doc payload (count+applied)",
            f"rerank_applied=true, rerank_input_count={_PREFILTER_POOL_TOP_N}",
            None, "unknown",
        ))

    # --- Stage 6: voyage raw response (NOT exposed) ------------------------- #
    stages.append(_stage(
        6, "voyage raw response (index/score)",
        "index in [0,30), relevance scores present",
        None,
        "unknown",  # not exposed by prod trace; black-box bracketed via stage4<->stage8
    ))

    # --- Stage 7: index -> chunks mapping (NOT exposed) --------------------- #
    stages.append(_stage(
        7, "index->chunks mapping",
        "voyage index i maps to retrieve_hybrid pool[i] (no off-by-one/dedup loss)",
        None,
        "unknown",  # static review: rag_rerank.py:249-256 bounds-checks idx + dedups
    ))

    # --- Stage 8: citation collector output --------------------------------- #
    citations = (trace_resp or {}).get("citations") or []
    matched_in_citations: list[str] = []
    for c in citations:
        m = _chunk_matches_gt(str(c.get("episode_id")), float(c.get("start_time", 0.0)), gt["primary"])
        if m and m not in matched_in_citations:
            matched_in_citations.append(m)
    if query_err:
        stages.append(_stage(8, "citation collector output", "GT chunks in citations", None,
                             "unknown"))
    else:
        actual8 = {
            "citation_count": len(citations),
            "citation_chunks": [
                {"episode_id": str(c.get("episode_id")), "start_time": c.get("start_time")}
                for c in citations
            ],
            "gt_matched": matched_in_citations,
            "gt_primary_total": len(gt["primary"]),
        }
        if gt["primary"] and len(matched_in_citations) == len(gt["primary"]):
            verdict8 = "match"
        elif matched_in_citations:
            verdict8 = "partial"
        else:
            verdict8 = "drift"  # no GT survived into citations
        stages.append(_stage(
            8, "citation collector output",
            "all GT chunks present in response.citations",
            actual8, verdict8,
        ))

    # --- Stage 9: grader-visible citations ---------------------------------- #
    # The eval runner grades response.citations directly, so stage 9 == stage 8.
    stages.append(_stage(
        9, "grader-visible citations",
        "grader input == collector output (response.citations)",
        {"identical_to_stage_8": True, "gt_matched": matched_in_citations,
         "note": "eval runner passes response.citations straight to grader"},
        "match" if not query_err else "unknown",
    ))

    # --- Overall verdict (black-box bracketing) ----------------------------- #
    overall = _bracket_root_cause(stages, prefilter_full)

    return {
        "item_id": item_id,
        "question": question,
        "query_error": query_err,
        "stages": stages,
        "overall_verdict": overall,
    }


def _bracket_root_cause(stages: list[dict], prefilter_full: dict | None) -> str:
    """Discriminate root cause from observable stages 4 (in) and 8 (out).

    Compares how many GT chunks were in the ideal retrieve_hybrid top-30 pool
    (stage 4) against how many survived into response.citations (stage 8):
      - matched < in_pool  -> voyage (or post-pool) dropped pool-resident GT
      - matched == in_pool < total -> the loss is below-top-30 retrieval, NOT
        voyage (voyage preserved every GT it actually received)
    Routing that bypasses the prefilter+voyage path is reported first, since
    then the voyage in/out bracket does not apply.
    """
    s = {st["stage"]: st for st in stages}

    # Routing bypass: the agent never invoked search_with_topic_prefilter.
    if s[2]["verdict"] == "drift" and isinstance(s[2]["actual"], dict) \
            and s[2]["actual"].get("prefilter_invoked") is False:
        tools = ",".join(s[2]["actual"].get("tools_invoked") or [])
        a4 = s[4]["actual"] or {}
        pool_note = ""
        if isinstance(a4, dict) and a4.get("gt_in_pool") == 0:
            pool_note = " + ideal-pool retrieval_miss (GT also absent from top-30)"
        return f"did_not_enter_voyage_path (routing -> {tools}){pool_note}"

    fallback = bool(prefilter_full and prefilter_full.get("fallback_to_full_pool"))
    applied = prefilter_full and prefilter_full.get("rerank_applied")
    if fallback or (prefilter_full is not None and not applied):
        return "did_not_enter_voyage_path (fallback_to_full_pool / rerank not applied)"

    a4 = s[4]["actual"] or {}
    a8 = s[8]["actual"] or {}
    in_pool = a4.get("gt_in_pool")
    total = a4.get("gt_total")
    matched = len(a8.get("gt_matched") or []) if isinstance(a8, dict) else None

    if in_pool == 0:
        return "retrieval_miss (GT absent from ideal retrieve_hybrid top-30 pool — not a voyage issue)"
    if matched is not None and in_pool is not None:
        if matched < in_pool:
            return ("voyage_demoted_gt (GT present in ideal top-30 pool but absent from "
                    "citations; caveat: agent's real prefilter breadth may exceed the "
                    "ideal pool — see stage 3 candidate count)")
        if total is not None and matched == in_pool < total:
            return ("retrieval_partial (voyage preserved all in-pool GT; residual loss is "
                    "below-top-30 retrieval, NOT voyage)")
        if total is not None and matched == in_pool == total:
            return "pipeline_ok (all GT survived end-to-end)"
    return "inconclusive (insufficient observable data)"


# --------------------------------------------------------------------------- #
# Output                                                                       #
# --------------------------------------------------------------------------- #
def _fmt_cell(v: Any, width: int = 60) -> str:
    if v is None:
        return "None"
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    s = s.replace("\n", " ").replace("|", "\\|")
    return s if len(s) <= width else s[: width - 1] + "…"


def _markdown(items: list[dict]) -> str:
    lines: list[str] = []
    for it in items:
        lines.append(f"\n### {it['item_id']} — {it.get('question', '')}")
        lines.append(f"\n**overall_verdict:** `{it['overall_verdict']}`")
        if it.get("query_error"):
            lines.append(f"\n**query_error:** `{it['query_error']}`")
        lines.append("\n| stage | name | expected | actual | verdict |")
        lines.append("|---|---|---|---|---|")
        for st in it["stages"]:
            lines.append(
                f"| {st['stage']} | {_fmt_cell(st['name'], 36)} | "
                f"{_fmt_cell(st['expected'], 60)} | {_fmt_cell(st['actual'], 90)} | "
                f"`{st['verdict']}` |"
            )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--item-ids", default="b21,b22,b23")
    ap.add_argument("--backend", default="https://podcastrag-api.zeabur.app")
    ap.add_argument("--out", default="/tmp/voyage-audit.json")
    ap.add_argument("--session-cookie-file", default="/tmp/podcastrag_session.txt")
    ap.add_argument("--me-json", default="/tmp/me_resp.json")
    args = ap.parse_args()

    cookie, csrf = _read_session_and_csrf(Path(args.session_cookie_file), Path(args.me_json))
    _preflight_me(args.backend, cookie, csrf)

    items_by_id, show_id = _load_dataset()
    item_ids = [s.strip() for s in args.item_ids.split(",") if s.strip()]

    out_items: list[dict] = []
    for iid in item_ids:
        item = items_by_id.get(iid)
        if item is None:
            out_items.append({"item_id": iid, "error": "not in dataset", "stages": []})
            print(f"[{iid}] not in dataset", file=sys.stderr)
            continue
        print(f"[{iid}] auditing…", file=sys.stderr)
        out_items.append(
            _audit_item(iid, item, backend=args.backend, show_id=show_id, cookie=cookie, csrf=csrf)
        )

    payload = {"backend": args.backend, "show_id": show_id, "items": out_items}
    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md = _markdown(out_items)
    Path(str(out_path) + ".md").write_text(md, encoding="utf-8")
    print(f"wrote {out_path} and {out_path}.md")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
