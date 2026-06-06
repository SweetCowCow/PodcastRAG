"""HyDE conditional-activation threshold calibration.

change: hyde-conditional-activation (task 5.1 / 5.2).

Conditional HyDE fires only when the query↔top-N base-recall lexical overlap is
below `hyde_mismatch_overlap_threshold`. This script measures that overlap for
the 10 lexical-mismatch TARGETS (HyDE should help → want overlap LOW so it fires)
and the 8 CALIBRATION questions (lexical already aligns → want overlap HIGH so
HyDE does NOT fire), then sweeps candidate cutoffs and reports, per cutoff:

  - target activation rate:        fraction of targets with overlap < cutoff
                                   (higher = more mismatch questions get HyDE)
  - calibration false-activation:  fraction of calibration with overlap < cutoff
                                   (lower = fewer aligned questions wrongly get HyDE)

The chosen cutoff maximises target activation while keeping calibration
false-activation near zero — i.e. it separates the two overlap distributions.

The overlap_ratio is read from `/admin/diagnose/prefilter-rank`, which computes
it from a base recall independent of the live flags (so this runs against prod
with conditional mode still OFF). Per reference_prod_eval_session, GET /me is
verified before any measurement; a stale session aborts loudly with no partial
output. The measurement makes NO HyDE LLM call (both flags off), so it is cheap.

Usage:
    python -m scripts.hyde_ab.calibrate_threshold run \
        --backend https://podcastrag-api.zeabur.app
    python -m scripts.hyde_ab.calibrate_threshold report \
        --run scripts/hyde_ab/results/calibrate-<ts>.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import audit_voyage_pipeline as av  # noqa: E402

# Same splits as the landing A/B (run.py), human-verified-2026-06-05, show 45fc2462.
DEFAULT_TARGETS = ("b20", "b23", "b32", "b33", "b37", "b38", "b39", "b40", "b41", "b42")
DEFAULT_CALIBRATION = ("b05", "b14", "b15", "b16", "b17", "b18", "b19", "b21")
DEFAULT_TOP_N = 200
# Candidate cutoffs swept; the data-chosen value backfills config + spec.
CANDIDATE_CUTOFFS = (0.1, 0.2, 0.3, 0.4, 0.5)
_TPE = timezone(timedelta(hours=8))


def _prepare_prod_session(backend: str, state_path: Path) -> tuple[str, str]:
    """(cookie_header, csrf) from playwright-state.json, CSRF live from GET /me.
    Aborts loudly on bad/expired session — no partial output."""
    data = json.loads(state_path.read_text(encoding="utf-8"))
    cookies = {c["name"]: c["value"] for c in data.get("cookies", [])}
    sid = cookies.get("session_id")
    if not sid:
        raise SystemExit(f"FATAL: no session_id cookie in {state_path}")
    try:
        me = av._request("GET", f"{backend}/me", f"session_id={sid}", "", timeout=30.0)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise SystemExit(
            f"FATAL: GET /me failed ({exc}). Session likely expired — "
            f"refresh playwright-state.json before rerunning."
        )
    if me.get("role") != "admin":
        raise SystemExit(f"FATAL: /me role={me.get('role')!r}, not admin.")
    return (
        f"session_id={sid}; csrf_token={me.get('csrf_token','')}",
        me.get("csrf_token", ""),
    )


def _measure(backend, cookie, csrf, items, top_n) -> dict[str, dict]:
    """POST prefilter-rank once for all items; returns {item_id: row}."""
    try:
        resp = av._request(
            "POST",
            f"{backend}/admin/diagnose/prefilter-rank",
            cookie, csrf,
            body={"items": list(items), "top_n": top_n},
            timeout=600.0,
        )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"FATAL: prefilter-rank call failed ({exc}). No results written.")
    return {row["item_id"]: row for row in resp.get("items", [])}


def _verify_overlap_present(rows: dict[str, dict]) -> None:
    """Abort loudly if the endpoint returned no overlap_ratio — means the prod
    build predates this change's diagnose endpoint update (redeploy needed)."""
    have = [r for r in rows.values() if r.get("overlap_ratio") is not None]
    if not have:
        raise SystemExit(
            "FATAL: no item returned overlap_ratio. The prod build likely predates "
            "the hyde-conditional-activation diagnose endpoint update — redeploy "
            "before calibrating. No results written."
        )


def _do_run(args) -> int:
    targets = [s.strip() for s in args.targets.split(",") if s.strip()]
    calibration = [s.strip() for s in args.calibration.split(",") if s.strip()]
    all_items = list(dict.fromkeys(targets + calibration))

    ps = Path(args.playwright_state)
    if ps.exists():
        cookie, csrf = _prepare_prod_session(args.backend, ps)
    else:
        cookie, csrf = av._read_session_and_csrf(Path(args.session_cookie_file), Path(args.me_json))
        av._preflight_me(args.backend, cookie, csrf)

    print(f"[calibrate] items={len(all_items)} top_n={args.top_n} ...", file=sys.stderr)
    rows = _measure(args.backend, cookie, csrf, all_items, args.top_n)
    _verify_overlap_present(rows)

    now = datetime.now(_TPE)
    ts = now.strftime("%Y%m%dT%H%M%S")
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else results_dir / f"calibrate-{ts}.json"
    out.write_text(json.dumps({
        "meta": {
            "ts": now.strftime("%Y-%m-%d %H:%M:%S (UTC+8)"),
            "backend": args.backend,
            "top_n": args.top_n,
            "targets": targets,
            "calibration": calibration,
            "candidate_cutoffs": list(CANDIDATE_CUTOFFS),
        },
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[calibrate] results -> {out}", file=sys.stderr)
    # Also echo the sweep table to stdout for a quick read.
    print(_build_report(json.loads(out.read_text(encoding="utf-8")),
                        now.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")))
    return 0


def _overlap(row: dict) -> float | None:
    v = row.get("overlap_ratio")
    return float(v) if v is not None else None


def _avg_must_rank(row: dict, top_n: int) -> float | None:
    ranks = [g.get("rank") for g in row.get("gt_ranks", []) if g.get("kind") == "must"]
    if not ranks:
        return None
    return sum((rk if rk is not None else top_n + 1) for rk in ranks) / len(ranks)


def _build_report(run: dict, ts_str: str) -> str:
    meta = run.get("meta", {})
    rows = run.get("rows", {})
    top_n = meta.get("top_n", DEFAULT_TOP_N)
    targets = meta.get("targets", list(DEFAULT_TARGETS))
    calibration = meta.get("calibration", list(DEFAULT_CALIBRATION))
    cutoffs = meta.get("candidate_cutoffs", list(CANDIDATE_CUTOFFS))
    L: list[str] = []
    L.append("# HyDE conditional-activation 門檻校準報告")
    L.append("")
    L.append(f"- 產出時間（台北）：{ts_str}")
    L.append(f"- backend：{meta.get('backend','?')}")
    L.append(f"- top_n（base 召回深度，overlap 取前 N）：{top_n}")
    L.append(f"- 標靶集（{len(targets)}，詞彙失配，期望 overlap 低→開 HyDE）：{', '.join(targets)}")
    L.append(f"- calibration 集（{len(calibration)}，lexical 對齊，期望 overlap 高→不開）：{', '.join(calibration)}")
    L.append("")

    # --- 1. per-item overlap ---
    L.append("## 1. 每題 overlap_ratio")
    L.append("")
    L.append("| item | 組別 | overlap_ratio | must 均 prefilter-rank |")
    L.append("|------|------|---------------|------------------------|")
    for iid in targets + calibration:
        r = rows.get(iid, {})
        grp = "標靶" if iid in targets else "calibration"
        ov = _overlap(r)
        ar = _avg_must_rank(r, top_n)
        ovs = "—（error）" if ov is None else f"{ov:.3f}"
        ars = "—" if ar is None else f"{ar:.1f}"
        if r.get("error"):
            ovs = f"error: {r['error']}"
        L.append(f"| {iid} | {grp} | {ovs} | {ars} |")
    L.append("")

    # --- 2. cutoff sweep ---
    L.append("## 2. cutoff 掃描（活化率對照）")
    L.append("")
    L.append("> 標靶啟用率 = overlap < cutoff 的標靶比例（越高越好，代表失配題有開到 HyDE）。"
             "calibration 誤啟用率 = overlap < cutoff 的 calibration 比例（越低越好）。")
    L.append("")
    L.append("| cutoff | 標靶啟用率 | calibration 誤啟用率 | 分離度(啟用−誤啟用) |")
    L.append("|--------|-----------|----------------------|---------------------|")
    t_ov = [(_overlap(rows.get(i, {}))) for i in targets]
    c_ov = [(_overlap(rows.get(i, {}))) for i in calibration]
    t_ov = [x for x in t_ov if x is not None]
    c_ov = [x for x in c_ov if x is not None]
    best = None
    for cut in cutoffs:
        t_rate = sum(1 for x in t_ov if x < cut) / len(t_ov) if t_ov else 0.0
        c_rate = sum(1 for x in c_ov if x < cut) / len(c_ov) if c_ov else 0.0
        sep = t_rate - c_rate
        if best is None or sep > best[1]:
            best = (cut, sep)
        L.append(f"| {cut:.1f} | {t_rate:.2f} | {c_rate:.2f} | {sep:+.2f} |")
    L.append("")
    if best is not None:
        L.append(f"- **分離度最高的 cutoff = {best[0]:.1f}**（標靶啟用−calibration 誤啟用 = {best[1]:+.2f}）。"
                 f"建議回填 `hyde_mismatch_overlap_threshold`。")
    L.append("")
    L.append("> 註：cutoff 過大會讓 calibration 也被開（誤啟用上升、傷 b05 類題）；"
             "過小則標靶開不到。選分離度最高且 calibration 誤啟用率接近 0 者。"
             "本樣本僅 18 題，門檻為 config 可調，正式上線仍須 prod A/B 複驗（不外推）。")
    L.append("")
    return "\n".join(L)


def _do_report(args) -> int:
    run = json.loads(Path(args.run).read_text(encoding="utf-8"))
    now = datetime.now(_TPE)
    ts_str = now.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    repo_root = Path(__file__).resolve().parents[3]
    out = (Path(args.out_report) if args.out_report
           else repo_root / "docs" / "case-studies" / "hyde-conditional-activation-calibration.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_build_report(run, ts_str), encoding="utf-8")
    print(f"[calibrate] report -> {out}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="HyDE conditional-activation threshold calibration")
    sub = ap.add_subparsers(dest="mode", required=True)

    r = sub.add_parser("run", help="measure overlap for targets+calibration against prod")
    r.add_argument("--backend", default="https://podcastrag-api.zeabur.app")
    r.add_argument("--targets", default=",".join(DEFAULT_TARGETS))
    r.add_argument("--calibration", default=",".join(DEFAULT_CALIBRATION))
    r.add_argument("--top-n", dest="top_n", type=int, default=DEFAULT_TOP_N)
    r.add_argument("--playwright-state",
                   default=str(Path.home() / ".config" / "podcastrag" / "playwright-state.json"))
    r.add_argument("--session-cookie-file", default="/tmp/podcastrag_session.txt")
    r.add_argument("--me-json", default="/tmp/me_resp.json")
    r.add_argument("--out", default=None)

    rep = sub.add_parser("report", help="rebuild the calibration markdown from a run JSON")
    rep.add_argument("--run", required=True)
    rep.add_argument("--out-report", default=None)

    args = ap.parse_args()
    if args.mode == "run":
        return _do_run(args)
    if args.mode == "report":
        return _do_report(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
