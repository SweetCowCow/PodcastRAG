"""Lexical-mismatch query-rewrite bake-off — harness orchestrator.

change: lexical-mismatch-query-rewrite-bakeoff (EQ3b family).

Offline, read-only. For each arm × case it POSTs the admin
`/admin/diagnose/lexical-bakeoff` endpoint (which does the rewrite → embed →
retrieve_hybrid server-side), collects each GT chunk's prefilter-rank + cost,
computes chunk_recall@must, runs the calibration non-regression check, picks a
winner, and emits a machine-readable JSON + a human-readable markdown report.

It DOES NOT land any arm into the prod retrieve path (stop-the-line).

Prod session reuses the audit_voyage_pipeline.py template (Netscape cookie jar +
me_json for CSRF). Per reference_prod_eval_session, GET /me is verified before
any measurement; a stale session aborts loudly with no partial report.

Usage:
    python -m scripts.lexical_bakeoff.run \
        --backend https://podcastrag-api.zeabur.app \
        --session-cookie-file /tmp/podcastrag_session.txt \
        --me-json /tmp/me_resp.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Reuse the prod-session + HTTP template from the sibling audit script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import audit_voyage_pipeline as av  # noqa: E402

ARMS = ("control", "query-expansion", "hyde", "multi-vector")
DEFAULT_TARGETS = ("b20", "b23")
# calibration_8 (backend/eval/datasets/_calibration_8.json) — items control
# already retrieves; used as the non-regression guard.
DEFAULT_CALIBRATION = ("b01", "b06", "b08", "b11", "b18", "b20", "b27", "mt03")

_TPE = timezone(timedelta(hours=8))


def _prepare_prod_session(backend: str, state_path: Path) -> tuple[str, str]:
    """Build (cookie_header, csrf) from playwright-state.json's session_id, taking
    the CSRF token LIVE from GET /me (the cookie's csrf_token can be stale → 403).
    Also verifies admin role. Aborts loudly on a bad/expired session — no partial
    report (reference_prod_eval_session; double-submit CSRF confirmed via smoke)."""
    data = json.loads(state_path.read_text(encoding="utf-8"))
    cookies = {c["name"]: c["value"] for c in data.get("cookies", [])}
    sid = cookies.get("session_id")
    if not sid:
        raise SystemExit(f"FATAL: no session_id cookie in {state_path}")
    try:
        me = av._request("GET", f"{backend}/me", f"session_id={sid}", "", timeout=30.0)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise SystemExit(f"FATAL: GET /me failed ({exc}). Session likely expired — "
                         f"refresh playwright-state.json before rerunning.")
    if me.get("role") != "admin":
        raise SystemExit(f"FATAL: /me role={me.get('role')!r}, not admin.")
    csrf = me.get("csrf_token", "")
    return f"session_id={sid}; csrf_token={csrf}", csrf


def _must_recall(gt_ranks: list[dict], top_n: int) -> float | None:
    must = [g for g in gt_ranks if g.get("kind") == "must"]
    if not must:
        return None
    hit = sum(1 for g in must if g.get("rank") is not None and g["rank"] <= top_n)
    return hit / len(must)


def _must_ranks(gt_ranks: list[dict]) -> list[int | None]:
    return [g.get("rank") for g in gt_ranks if g.get("kind") == "must"]


def _call_arm(backend, cookie, csrf, arm, items, top_n) -> dict[str, dict]:
    """POST one arm for all items. Returns {item_id: cell}. Arm-level HTTP
    failure marks every item ERROR for that arm but never aborts the batch."""
    try:
        resp = av._request(
            "POST",
            f"{backend}/admin/diagnose/lexical-bakeoff",
            cookie, csrf,
            body={"arm": arm, "items": list(items), "top_n": top_n},
            timeout=600.0,
        )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return {it: {"item_id": it, "arm": arm, "error": f"arm-call failed: {exc}"} for it in items}
    return {row["item_id"]: row for row in resp.get("items", [])}


def _arm_target_score(arm, targets, matrix, top_n) -> tuple[float, float]:
    """(avg must-recall, avg must-rank) over target cases. Miss → top_n+1."""
    recalls: list[float] = []
    ranks: list[int] = []
    for it in targets:
        cell = matrix.get(arm, {}).get(it, {})
        if cell.get("error") or "gt_ranks" not in cell:
            continue
        r = _must_recall(cell["gt_ranks"], top_n)
        if r is not None:
            recalls.append(r)
        for rk in _must_ranks(cell["gt_ranks"]):
            ranks.append(rk if rk is not None else top_n + 1)
    avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
    avg_rank = sum(ranks) / len(ranks) if ranks else float(top_n + 1)
    return avg_recall, avg_rank


def _calibration_verdict(arm, calibration, matrix, top_n) -> dict[str, Any]:
    """Compare arm vs control must-recall on calibration items. Regress if lower."""
    regressed: list[str] = []
    compared = 0
    for it in calibration:
        ctrl = matrix.get("control", {}).get(it, {})
        cand = matrix.get(arm, {}).get(it, {})
        if ctrl.get("error") or cand.get("error"):
            continue
        cr = _must_recall(ctrl.get("gt_ranks", []), top_n)
        ar = _must_recall(cand.get("gt_ranks", []), top_n)
        if cr is None or ar is None:
            continue
        compared += 1
        if ar < cr:
            regressed.append(it)
    return {
        "verdict": "退步" if regressed else "未退步",
        "regressed_items": regressed,
        "compared": compared,
    }


def _fmt_ranks(gt_ranks: list[dict]) -> str:
    parts = []
    for g in gt_ranks:
        if g.get("kind") != "must":
            continue
        rk = g.get("rank")
        cid = g.get("gt_chunk_id", "").split("@")[-1]
        parts.append(f"@{cid}={'miss' if rk is None else rk}")
    return ", ".join(parts) or "—"


def build_report(matrix, targets, calibration, arms, top_n, backend, ts_str) -> str:
    L: list[str] = []
    L.append("# 詞彙失配 query 改寫 bake-off 報告")
    L.append("")
    L.append(f"- 產出時間（台北）：{ts_str}")
    L.append(f"- backend：{backend}")
    L.append(f"- top_n（候選池深度）：{top_n}")
    L.append(f"- arms：{', '.join(arms)}")
    L.append(f"- 標靶案例：{', '.join(targets)}；calibration 防退步集：{', '.join(calibration)}")
    L.append("")
    L.append("> change：lexical-mismatch-query-rewrite-bakeoff。本報告為離線量測，"
             "**未變更任何 prod retrieve path**。")
    L.append("")

    # --- 標靶矩陣 ---
    L.append("## 1. 標靶案例 arm × case 矩陣（must chunk）")
    L.append("")
    L.append("| case | arm | recall@must | must prefilter-rank | 額外LLM call | LLM延遲(ms) |")
    L.append("|------|-----|-------------|---------------------|-------------|-------------|")
    for it in targets:
        for arm in arms:
            cell = matrix.get(arm, {}).get(it, {})
            if cell.get("error"):
                L.append(f"| {it} | {arm} | ERROR | {cell['error']} | — | — |")
                continue
            gr = cell.get("gt_ranks", [])
            rec = _must_recall(gr, top_n)
            cost = cell.get("cost", {})
            L.append(
                f"| {it} | {arm} | {'—' if rec is None else f'{rec:.2f}'} "
                f"| {_fmt_ranks(gr)} | {cost.get('extra_llm_calls','—')} "
                f"| {cost.get('latency_ms','—')} |"
            )
    L.append("")

    # --- 勝者判定 ---
    L.append("## 2. 勝者判定（量化依據）")
    L.append("")
    scores = {arm: _arm_target_score(arm, targets, matrix, top_n) for arm in arms}
    ctrl_recall, ctrl_rank = scores.get("control", (0.0, float(top_n + 1)))
    L.append(f"- control 基準：標靶平均 recall@must = **{ctrl_recall:.2f}**，"
             f"平均 must prefilter-rank = **{ctrl_rank:.1f}**（miss 計為 {top_n+1}）。")
    L.append("")
    L.append("| arm | 標靶平均 recall@must | 標靶平均 must-rank |")
    L.append("|-----|----------------------|--------------------|")
    for arm in arms:
        r, rk = scores[arm]
        L.append(f"| {arm} | {r:.2f} | {rk:.1f} |")
    L.append("")
    candidates = [a for a in arms if a != "control"]
    # winner: beats control recall, tie-break by lower avg rank.
    beats = [a for a in candidates
             if scores[a][0] > ctrl_recall
             or (abs(scores[a][0] - ctrl_recall) < 1e-9 and scores[a][1] < ctrl_rank)]
    if beats:
        winner = sorted(beats, key=lambda a: (-scores[a][0], scores[a][1]))[0]
        wr, wrk = scores[winner]
        L.append(f"**勝者（量化）= `{winner}`** — 標靶平均 recall@must {wr:.2f}（control {ctrl_recall:.2f}）、"
                 f"平均 must-rank {wrk:.1f}（control {ctrl_rank:.1f}）。")
    else:
        winner = None
        L.append("**無 arm 在標靶上勝過 control** — 量化層面沒有手段把標靶 chunk 拉得更前。")
    L.append("")

    # --- calibration 退步 ---
    L.append("## 3. calibration 防退步檢查（vs control）")
    L.append("")
    L.append("> 退步只對「有 must chunk 且 control、arm 雙方都成功量到」的 calibration item 計算；"
             "enumeration/negative 題（must=0，如 b06/b08/b11/b27）不進比對，「比對數」欄揭露實際樣本數。")
    L.append("")
    L.append("| arm | 結論 | 退步案例 | 比對數 |")
    L.append("|-----|------|----------|--------|")
    cal_verdicts = {}
    for arm in candidates:
        v = _calibration_verdict(arm, calibration, matrix, top_n)
        cal_verdicts[arm] = v
        L.append(f"| {arm} | {v['verdict']} | {', '.join(v['regressed_items']) or '—'} | {v['compared']} |")
    L.append("")

    # --- 評分視角 ---
    L.append("## 4. 評分視角（mixed）")
    L.append("")
    L.append("- **量化層（arm 優劣）**：第 2 節純看標靶 recall@must 與 must prefilter-rank，"
             "數據判定，不摻入價值判斷。")
    L.append("- **落地層（human 判斷）**：query-expansion / hyde / multi-vector 每次查詢多 1 次 LLM call"
             "（見矩陣的成本欄），是否值得落地、落地哪個 arm，須由人權衡「召回收益 vs 成本/延遲」，"
             "不能只看 recall 數字（依 feedback_bakeoff_perspective_calibration）。")
    L.append("")

    # --- 限制 ---
    L.append("## 5. 限制聲明")
    L.append("")
    L.append(f"- **小樣本**：標靶僅 {len(targets)} 案（{', '.join(targets)}），結論限定「這兩案的詞彙失配」，"
             "**不外推**到未測題型。")
    L.append("- HyDE / expansion / multi-vector 用 LLM 生成，已固定 prompt + temperature=0 + 記錄 model"
             "（見 results JSON 的 rewrite_debug）；仍可能有生成變異。")
    L.append("")

    # --- stop-the-line ---
    L.append("## 6. stop-the-line")
    L.append("")
    if winner:
        L.append(f"上述勝者 `{winner}` **僅為待人工核准之建議**。本 bake-off 未把任何 arm 落地到 "
                 "prod retrieve path；是否落地、由哪條後續 change 落地，等 Jacky 拍板。")
    else:
        L.append("無勝者建議。本 bake-off 未變更任何 prod retrieve path；下一步方向等 Jacky 拍板。")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Lexical-mismatch query-rewrite bake-off harness")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--targets", default=",".join(DEFAULT_TARGETS))
    ap.add_argument("--calibration", default=",".join(DEFAULT_CALIBRATION))
    ap.add_argument("--backend", default="https://podcastrag-api.zeabur.app")
    ap.add_argument("--top-n", type=int, default=200)
    ap.add_argument("--playwright-state",
                    default=str(Path.home() / ".config" / "podcastrag" / "playwright-state.json"))
    ap.add_argument("--session-cookie-file", default="/tmp/podcastrag_session.txt")
    ap.add_argument("--me-json", default="/tmp/me_resp.json")
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-report", default=None)
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    targets = [a.strip() for a in args.targets.split(",") if a.strip()]
    calibration = [a.strip() for a in args.calibration.split(",") if a.strip()]
    all_items = list(dict.fromkeys(targets + calibration))

    bad = [a for a in arms if a not in ARMS]
    if bad:
        print(f"FATAL: unknown arm(s) {bad}; expected subset of {list(ARMS)}", file=sys.stderr)
        return 2

    # Prod session preflight — fail loud, no partial report (reference_prod_eval_session).
    # Prefer playwright-state.json (prod eval flow); fall back to the audit script's
    # Netscape cookie jar template.
    ps = Path(args.playwright_state)
    if ps.exists():
        cookie, csrf = _prepare_prod_session(args.backend, ps)
    else:
        cookie, csrf = av._read_session_and_csrf(Path(args.session_cookie_file), Path(args.me_json))
        av._preflight_me(args.backend, cookie, csrf)

    matrix: dict[str, dict[str, dict]] = {}
    for arm in arms:
        print(f"[bakeoff] arm={arm} items={all_items} ...", file=sys.stderr)
        matrix[arm] = _call_arm(args.backend, cookie, csrf, arm, all_items, args.top_n)

    now = datetime.now(_TPE)
    ts_compact = now.strftime("%Y%m%dT%H%M%S")
    ts_str = now.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    date_str = now.strftime("%Y-%m-%d")

    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_json = Path(args.out_json) if args.out_json else results_dir / f"bakeoff-{ts_compact}.json"
    repo_root = Path(__file__).resolve().parents[3]
    out_report = (Path(args.out_report) if args.out_report
                  else repo_root / "docs" / "case-studies" / f"lexical-mismatch-bakeoff-{date_str}.md")
    out_report.parent.mkdir(parents=True, exist_ok=True)

    out_json.write_text(json.dumps({
        "meta": {"ts": ts_str, "backend": args.backend, "top_n": args.top_n,
                 "arms": arms, "targets": targets, "calibration": calibration},
        "matrix": matrix,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    report = build_report(matrix, targets, calibration, arms, args.top_n, args.backend, ts_str)
    out_report.write_text(report, encoding="utf-8")

    print(f"[bakeoff] results -> {out_json}", file=sys.stderr)
    print(f"[bakeoff] report  -> {out_report}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
