"""HyDE landing flag on/off A/B harness.

change: hyde-retrieval-landing (task 5.1 / 5.2).

Measures each target item's must-chunk **prefilter-rank** on the LANDED retrieve
path, under `enable_hyde_retrieval` off vs on. It POSTs the admin
`/admin/diagnose/prefilter-rank` endpoint, which (post hyde-retrieval-landing)
embeds the question via the flag-gated `resolve_semantic_embedding`, so its
output reflects the *current server flag state*. The A/B is therefore done by:

    1. deploy with ENABLE_HYDE_RETRIEVAL=false → `run --label off`
    2. toggle env true → redeploy → verify env truth → `run --label on`
    3. `report --off <off.json> --on <on.json>` → docs case-study

Per feedback_env_toggle_order_discipline the harness VERIFIES the flag actually
took effect: the endpoint returns `used_hyde` per item; an `--label on` run where
no item used HyDE (or an `--label off` run where any did) aborts loudly — a
redeploy that didn't re-read env would otherwise silently produce a junk A/B.

Per reference_prod_eval_session, GET /me is verified before any measurement; a
stale/expired session aborts loudly with NO partial results file written.

Usage:
    python -m scripts.hyde_ab.run run --label off \
        --backend https://podcastrag-api.zeabur.app
    python -m scripts.hyde_ab.run run --label on  --backend https://podcastrag-api.zeabur.app
    python -m scripts.hyde_ab.run report \
        --off scripts/hyde_ab/results/hyde-ab-off-<ts>.json \
        --on  scripts/hyde_ab/results/hyde-ab-on-<ts>.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Reuse the prod-session + HTTP template from the audit script (same as the
# lexical bake-off harness).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import audit_voyage_pipeline as av  # noqa: E402

# 10-item lexical-mismatch target set (human-verified-2026-06-05, all show
# 45fc2462). b20/b23 = original bake-off targets; b32+ = co-draft expansion.
DEFAULT_TARGETS = ("b20", "b23", "b32", "b33", "b37", "b38", "b39", "b40", "b41", "b42")
# Non-regression guard: must-chunk items control already retrieves well
# (EP-scoped deep-dives + b21); HyDE must not push their GT chunk back.
DEFAULT_CALIBRATION = ("b05", "b14", "b15", "b16", "b17", "b18", "b19", "b21")
DEFAULT_TOP_N = 200
_CUTOFFS = (5, 20, 50, 100)
_MISS = "miss"
_TPE = timezone(timedelta(hours=8))


def _prepare_prod_session(backend: str, state_path: Path) -> tuple[str, str]:
    """Build (cookie_header, csrf) from playwright-state.json's session_id, taking
    CSRF LIVE from GET /me. Aborts loudly on bad/expired session — no partial
    output (reference_prod_eval_session)."""
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
    return f"session_id={sid}; csrf_token={me.get('csrf_token','')}", me.get("csrf_token", "")


def _measure(backend, cookie, csrf, items, top_n) -> dict[str, dict]:
    """POST the prefilter-rank endpoint for all items. One HTTP call. Returns
    {item_id: row}. A transport failure aborts loudly (no partial file)."""
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


def _verify_flag(label: str, rows: dict[str, dict]) -> None:
    """feedback_env_toggle_order_discipline: confirm the server flag matches the
    declared label. Abort loudly on mismatch — a redeploy that didn't re-read
    env would otherwise yield a silent junk A/B."""
    measured = [r for r in rows.values() if "used_hyde" in r and not r.get("error")]
    if not measured:
        raise SystemExit("FATAL: no measurable items returned used_hyde; cannot verify flag.")
    any_hyde = any(r.get("used_hyde") for r in measured)
    all_hyde = all(r.get("used_hyde") for r in measured)
    if label == "on" and not any_hyde:
        raise SystemExit(
            "FATAL: --label on but NO item used HyDE (used_hyde all False). "
            "ENABLE_HYDE_RETRIEVAL did not take effect — did the redeploy re-read env? "
            "(feedback_env_toggle_order_discipline). No results written.")
    if label == "off" and any_hyde:
        offenders = [iid for iid, r in rows.items() if r.get("used_hyde")]
        raise SystemExit(
            f"FATAL: --label off but these items used HyDE: {offenders}. "
            "Server flag is ON. No results written.")
    if label == "on" and not all_hyde:
        # Not fatal — fail-open items (LLM error) legitimately fall back. Warn.
        fellback = [iid for iid, r in rows.items()
                    if "used_hyde" in r and not r.get("used_hyde") and not r.get("error")]
        print(f"[hyde-ab] WARN --label on: {len(fellback)} item(s) fell open to base_vec "
              f"(HyDE gen failed): {fellback}", file=sys.stderr)


# ----------------------------- run mode -----------------------------

def _do_run(args) -> int:
    if args.label not in ("off", "on"):
        raise SystemExit(f"FATAL: --label must be off|on, got {args.label!r}")
    targets = [s.strip() for s in args.targets.split(",") if s.strip()]
    calibration = [s.strip() for s in args.calibration.split(",") if s.strip()]
    all_items = list(dict.fromkeys(targets + calibration))

    # Preflight session FIRST — fail loud before any measurement / file write.
    ps = Path(args.playwright_state)
    if ps.exists():
        cookie, csrf = _prepare_prod_session(args.backend, ps)
    else:
        cookie, csrf = av._read_session_and_csrf(Path(args.session_cookie_file), Path(args.me_json))
        av._preflight_me(args.backend, cookie, csrf)

    print(f"[hyde-ab] label={args.label} items={len(all_items)} top_n={args.top_n} ...",
          file=sys.stderr)
    rows = _measure(args.backend, cookie, csrf, all_items, args.top_n)
    _verify_flag(args.label, rows)  # aborts before writing if flag state is wrong

    now = datetime.now(_TPE)
    ts = now.strftime("%Y%m%dT%H%M%S")
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else results_dir / f"hyde-ab-{args.label}-{ts}.json"
    out.write_text(json.dumps({
        "meta": {
            "label": args.label,
            "ts": now.strftime("%Y-%m-%d %H:%M:%S (UTC+8)"),
            "backend": args.backend,
            "top_n": args.top_n,
            "targets": targets,
            "calibration": calibration,
        },
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[hyde-ab] results -> {out}", file=sys.stderr)
    return 0


# ----------------------------- report mode -----------------------------

def _must_ranks(row: dict) -> list[tuple[str, int | None]]:
    """[(short_chunk_id, rank|None)] for must chunks."""
    out = []
    for g in row.get("gt_ranks", []):
        if g.get("kind") != "must":
            continue
        out.append((g.get("gt_chunk_id", "").split("@")[-1], g.get("rank")))
    return out


def _avg_must_rank(row: dict, top_n: int) -> float | None:
    ranks = [rk for _, rk in _must_ranks(row)]
    if not ranks:
        return None
    return sum((rk if rk is not None else top_n + 1) for rk in ranks) / len(ranks)


def _recall_at(row: dict, cut: int) -> float | None:
    ranks = [rk for _, rk in _must_ranks(row)]
    if not ranks:
        return None
    return sum(1 for rk in ranks if rk is not None and rk <= cut) / len(ranks)


def _fmt_ranks(row: dict) -> str:
    parts = [f"@{cid}={'miss' if rk is None else rk}" for cid, rk in _must_ranks(row)]
    return ", ".join(parts) or "—"


def _build_report(off: dict, on: dict, ts_str: str) -> str:
    meta = on.get("meta", {})
    top_n = meta.get("top_n", DEFAULT_TOP_N)
    targets = meta.get("targets", list(DEFAULT_TARGETS))
    calibration = meta.get("calibration", list(DEFAULT_CALIBRATION))
    off_rows, on_rows = off.get("rows", {}), on.get("rows", {})
    L: list[str] = []
    L.append("# HyDE landing flag on/off A/B 報告")
    L.append("")
    L.append(f"- 產出時間（台北）：{ts_str}")
    L.append(f"- backend：{meta.get('backend','?')}")
    L.append(f"- top_n（候選池深度）：{top_n}")
    L.append(f"- off run：{off.get('meta',{}).get('ts','?')}；on run：{meta.get('ts','?')}")
    L.append(f"- 標靶集（{len(targets)}）：{', '.join(targets)}")
    L.append(f"- calibration 防退步集（{len(calibration)}）：{', '.join(calibration)}")
    L.append("")
    L.append("> change：hyde-retrieval-landing。量測落在**已 landed 的 retrieve path**"
             "（`/admin/diagnose/prefilter-rank` 經 `resolve_semantic_embedding`），"
             "以 GT-episode 為 prefilter 隔離 chunk 召回層（routing 不在此量測範圍，見 D1）。")
    L.append("")

    # --- 1. 標靶 must prefilter-rank off vs on ---
    L.append("## 1. 標靶 must prefilter-rank：flag off vs on")
    L.append("")
    L.append("| item | off must-rank | on must-rank | off 均 | on 均 | Δ(↓較好) | used_hyde(on) |")
    L.append("|------|---------------|--------------|--------|-------|----------|---------------|")
    off_avgs, on_avgs = [], []
    for iid in targets:
        o, n = off_rows.get(iid, {}), on_rows.get(iid, {})
        if o.get("error") or n.get("error"):
            L.append(f"| {iid} | {o.get('error','?')} | {n.get('error','?')} | — | — | — | — |")
            continue
        oa, na = _avg_must_rank(o, top_n), _avg_must_rank(n, top_n)
        delta = "—" if (oa is None or na is None) else f"{na - oa:+.1f}"
        if oa is not None and na is not None:
            off_avgs.append(oa)
            on_avgs.append(na)
        L.append(f"| {iid} | {_fmt_ranks(o)} | {_fmt_ranks(n)} | "
                 f"{'—' if oa is None else f'{oa:.1f}'} | {'—' if na is None else f'{na:.1f}'} | "
                 f"{delta} | {n.get('used_hyde','?')} |")
    L.append("")
    if off_avgs and on_avgs:
        moff = sum(off_avgs) / len(off_avgs)
        mon = sum(on_avgs) / len(on_avgs)
        L.append(f"- **標靶平均 must prefilter-rank**：off = **{moff:.1f}** → on = **{mon:.1f}** "
                 f"（{mon - moff:+.1f}，負值代表 HyDE 把 GT chunk 拉得更前；miss 計為 top_n+1）。")
    L.append("")
    L.append("### recall@k 對照（標靶集平均）")
    L.append("")
    L.append("| cutoff | off recall@must | on recall@must |")
    L.append("|--------|-----------------|----------------|")
    for cut in _CUTOFFS:
        if cut > top_n:
            break
        o_r = [_recall_at(off_rows.get(i, {}), cut) for i in targets]
        n_r = [_recall_at(on_rows.get(i, {}), cut) for i in targets]
        o_r = [x for x in o_r if x is not None]
        n_r = [x for x in n_r if x is not None]
        om = f"{sum(o_r)/len(o_r):.2f}" if o_r else "—"
        nm = f"{sum(n_r)/len(n_r):.2f}" if n_r else "—"
        L.append(f"| top-{cut} | {om} | {nm} |")
    L.append("")

    # --- 2. calibration 防退步 ---
    L.append("## 2. calibration 防退步檢查（on vs off）")
    L.append("")
    L.append("> 退步 = 同一 item 的平均 must prefilter-rank 在 on 比 off 變差（變大）。"
             "只比對雙方都成功量到的 item。")
    L.append("")
    L.append("| item | off 均 must-rank | on 均 must-rank | 判定 |")
    L.append("|------|------------------|-----------------|------|")
    regressed = []
    for iid in calibration:
        o, n = off_rows.get(iid, {}), on_rows.get(iid, {})
        oa, na = _avg_must_rank(o, top_n), _avg_must_rank(n, top_n)
        if oa is None or na is None or o.get("error") or n.get("error"):
            L.append(f"| {iid} | {'—' if oa is None else f'{oa:.1f}'} | "
                     f"{'—' if na is None else f'{na:.1f}'} | 略過（無雙邊量測） |")
            continue
        worse = na > oa + 1e-9
        if worse:
            regressed.append(iid)
        L.append(f"| {iid} | {oa:.1f} | {na:.1f} | {'⚠ 退步' if worse else 'OK'} |")
    L.append("")
    L.append(f"**calibration 結論：{'⚠ 有退步 — ' + ', '.join(regressed) if regressed else '無退步'}**")
    L.append("")

    # --- 3. b23 選集層 caveat ---
    L.append("## 3. b23 註記：選集層 vs chunk 層")
    L.append("")
    L.append("> 本量測以 GT-episode 當 prefilter，**繞過選集 routing**，只看 chunk 召回。"
             "b23 真正卡點可能在 `find_episodes_by_topic` 選集層（只比 title/description），"
             "HyDE 接在 chunk 層、不一定解得到 b23 的選集 miss。判讀 b23 時須分清"
             "「選集層是否本來就召得回」與「chunk 層 HyDE 是否改善」兩件事，"
             "勿把選集層 miss 誤記為 HyDE 無效。")
    L.append("")

    # --- 4. 評分視角 mixed ---
    L.append("## 4. 評分視角（mixed）")
    L.append("")
    L.append("- **量化層**：第 1 節純看標靶 must prefilter-rank 與 recall@k 的 off→on 變化。")
    L.append("- **落地層（human 判斷）**：flag on 每次查詢多 1 次 LLM 生成（HyDE 文本，約 1.5–2s）"
             "+ 多 1 次 embed。是否 flip 預設，須權衡「召回收益（rank 前移幅度）vs 延遲/成本」，"
             "不能只看 rank 數字（feedback_bakeoff_perspective_calibration）。")
    L.append("")

    # --- 5. 限制 + HyDE 文本樣本 ---
    L.append("## 5. 限制聲明 + HyDE 文本樣本")
    L.append("")
    L.append(f"- **小樣本**：標靶 {len(targets)} 題詞彙失配題，結論限定此題型，**不外推**。")
    L.append("- HyDE 文本由 prod `answer` step 的 model 生成，固定 prompt（`_HYDE_SYSTEM`）+ "
             "temperature=0；仍可能有生成變異。以下為 on run 各 item 的 HyDE 文本樣本：")
    L.append("")
    for iid in targets:
        n = on_rows.get(iid, {})
        ht = (n.get("hyde_text") or "").strip().replace("\n", " ")
        if ht:
            L.append(f"  - **{iid}**：{ht[:160]}")
    L.append("")

    # --- 6. stop-the-line ---
    L.append("## 6. stop-the-line")
    L.append("")
    L.append("本 A/B 為量測，`enable_hyde_retrieval` 預設維持 **off**。是否 flip 預設為 True，"
             "為待 Jacky 依本報告證據核准之決定，由後續 change / 設定變更落地——本 change 不自動 flip。")
    L.append("")
    return "\n".join(L)


def _do_report(args) -> int:
    off = json.loads(Path(args.off).read_text(encoding="utf-8"))
    on = json.loads(Path(args.on).read_text(encoding="utf-8"))
    now = datetime.now(_TPE)
    ts_str = now.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    repo_root = Path(__file__).resolve().parents[3]
    out = (Path(args.out_report) if args.out_report
           else repo_root / "docs" / "case-studies" / "hyde-landing-ab-2026-06-05.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_build_report(off, on, ts_str), encoding="utf-8")
    print(f"[hyde-ab] report -> {out}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="HyDE landing flag on/off A/B harness")
    sub = ap.add_subparsers(dest="mode", required=True)

    r = sub.add_parser("run", help="measure one flag state (off|on) against prod")
    r.add_argument("--label", required=True, help="off|on — declared flag state; verified vs used_hyde")
    r.add_argument("--backend", default="https://podcastrag-api.zeabur.app")
    r.add_argument("--targets", default=",".join(DEFAULT_TARGETS))
    r.add_argument("--calibration", default=",".join(DEFAULT_CALIBRATION))
    r.add_argument("--top-n", dest="top_n", type=int, default=DEFAULT_TOP_N)
    r.add_argument("--playwright-state",
                   default=str(Path.home() / ".config" / "podcastrag" / "playwright-state.json"))
    r.add_argument("--session-cookie-file", default="/tmp/podcastrag_session.txt")
    r.add_argument("--me-json", default="/tmp/me_resp.json")
    r.add_argument("--out", default=None)

    rep = sub.add_parser("report", help="build on-vs-off markdown report from two run JSONs")
    rep.add_argument("--off", required=True)
    rep.add_argument("--on", required=True)
    rep.add_argument("--out-report", default=None)

    args = ap.parse_args()
    if args.mode == "run":
        return _do_run(args)
    if args.mode == "report":
        return _do_report(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
