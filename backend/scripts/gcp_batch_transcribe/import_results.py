#!/usr/bin/env python3
"""本機節流匯入：out/*.json → POST /admin/episodes/{id}/transcript-import。

D4：prod 憑證不上 VM——結果先 pull 回本機，由這支腳本匯入。
節流：併發 <= 2、集間 sleep（963 小時的 chunking + embedding 是真實負載，
避免 embedding API / AI Hub 突刺）。

進度落盤 import_manifest.jsonl（episode_id / status / task_id / error），
可中斷續跑；--retry-failed 重送失敗清單。

用法：
  python3 import_results.py --results-dir results/out --e2e-login
  python3 import_results.py --results-dir results/out --e2e-login --retry-failed
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://podcastrag-api.zeabur.app"
E2E_TOKEN_PATH = Path.home() / ".config/podcastrag/e2e-token"
MAX_CONCURRENCY = 2
SLEEP_BETWEEN = 2.0  # 秒；每集之間的最小間隔


def e2e_login(session: requests.Session, base_url: str) -> None:
    token = E2E_TOKEN_PATH.read_text().strip()
    r = session.get(
        f"{base_url}/auth/_e2e_login", params={"token": token}, timeout=30
    )
    r.raise_for_status()
    if "session_id" not in session.cookies:
        raise RuntimeError("e2e login 未取得 session cookie")


def csrf_headers(session: requests.Session, base_url: str) -> dict:
    # CSRF synchronizer token 是 session_id 的 HMAC 衍生值，前端（跟我們）
    # 都從 /me response body 拿，cookie 原值比不過（2026-07-02 實測 403）。
    r = session.get(f"{base_url}/me", timeout=30)
    r.raise_for_status()
    csrf = r.json().get("csrf_token", "")
    if not csrf:
        raise RuntimeError("/me 沒回 csrf_token — 先 --e2e-login")
    origin = "https://podcastrag.zeabur.app"
    return {"X-CSRF-Token": csrf, "Origin": origin}


def load_manifest(path: Path) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    if path.exists():
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    e = json.loads(line)
                    entries[e["episode_id"]] = e
    return entries


def append_manifest(path: Path, entry: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()


def import_one(
    session: requests.Session,
    base_url: str,
    headers: dict,
    ep_id: str,
    payload_path: Path,
) -> dict:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    r = session.post(
        f"{base_url}/admin/episodes/{ep_id}/transcript-import",
        json=payload,
        headers=headers,
        timeout=120,
    )
    if r.status_code == 202:
        return {
            "episode_id": ep_id,
            "status": "accepted",
            "task_id": r.json().get("task_id"),
            "error": None,
        }
    return {
        "episode_id": ep_id,
        "status": "failed",
        "task_id": None,
        "error": f"HTTP {r.status_code}: {r.text[:300]}",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, required=True,
                    help="runner 產出的 out/ 目錄（{episode_id}.json）")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--e2e-login", action="store_true")
    ap.add_argument("--manifest", type=Path,
                    default=Path(__file__).parent / "import_manifest.jsonl")
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只匯前 N 集（試水用）")
    ap.add_argument("--sleep", type=float, default=SLEEP_BETWEEN)
    args = ap.parse_args()

    session = requests.Session()
    if args.e2e_login:
        e2e_login(session, args.base_url)
    headers = csrf_headers(session, args.base_url)

    manifest = load_manifest(args.manifest)
    files = sorted(args.results_dir.glob("*.json"))
    pending = [
        p
        for p in files
        if p.stem not in manifest
        or (args.retry_failed and manifest[p.stem]["status"] == "failed")
    ]
    if args.limit:
        pending = pending[: args.limit]
    print(
        f"results={len(files)} imported={len(manifest)} pending={len(pending)} "
        f"concurrency={MAX_CONCURRENCY} sleep={args.sleep}s",
        file=sys.stderr,
    )

    ok = failed = 0
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        futures = {}
        for p in pending:
            futures[pool.submit(
                import_one, session, args.base_url, headers, p.stem, p
            )] = p
            time.sleep(args.sleep)  # 送件節流：ThreadPool 消化、submit 端限速
        for fut in as_completed(futures):
            entry = fut.result()
            append_manifest(args.manifest, entry)
            if entry["status"] == "accepted":
                ok += 1
            else:
                failed += 1
                print(
                    f"FAILED {entry['episode_id']}: {entry['error']}",
                    file=sys.stderr,
                )
    print(f"accepted={ok} failed={failed}", file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
