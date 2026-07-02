#!/usr/bin/env python3
"""從 prod 匯出集數清單 → episodes.jsonl（runner.py 的輸入）。

走 prod API（不碰 DB 憑證）：GET /shows/{show_id}/episodes 分頁抓全，
輸出每行 {episode_id, audio_url, duration_seconds, title,
transcript_status}。預設略過 transcript 已 completed 的集數（避免重轉）。

Session 取得（E2E backdoor SOP）：
  python3 export_episode_list.py --show-id <uuid> --e2e-login
會讀 ~/.config/podcastrag/e2e-token 打 /auth/_e2e_login 換 cookies；
token 全程不落 stdout。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://podcastrag-api.zeabur.app"
E2E_TOKEN_PATH = Path.home() / ".config/podcastrag/e2e-token"
PAGE_SIZE = 200


def e2e_login(session: requests.Session, base_url: str) -> None:
    token = E2E_TOKEN_PATH.read_text().strip()
    r = session.get(
        f"{base_url}/auth/_e2e_login", params={"token": token}, timeout=30
    )
    r.raise_for_status()
    if "session_id" not in session.cookies:
        raise RuntimeError("e2e login 未取得 session cookie")


def fetch_all_episodes(
    session: requests.Session, base_url: str, show_id: str
) -> list[dict]:
    episodes: list[dict] = []
    offset = 0
    while True:
        r = session.get(
            f"{base_url}/shows/{show_id}/episodes",
            params={"limit": PAGE_SIZE, "offset": offset},
            timeout=60,
        )
        r.raise_for_status()
        page = r.json()
        episodes.extend(page)
        if len(page) < PAGE_SIZE:
            return episodes
        offset += PAGE_SIZE


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-id", action="append", required=True,
                    help="可重複指定多個 show")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).parent / "episodes.jsonl")
    ap.add_argument("--e2e-login", action="store_true",
                    help="用 E2E backdoor token 換 session")
    ap.add_argument("--include-transcribed", action="store_true",
                    help="連 transcript 已 completed 的集數也匯出")
    args = ap.parse_args()

    session = requests.Session()
    if args.e2e_login:
        e2e_login(session, args.base_url)

    rows: list[dict] = []
    for show_id in args.show_id:
        episodes = fetch_all_episodes(session, args.base_url, show_id)
        kept = 0
        for ep in episodes:
            if (
                not args.include_transcribed
                and ep.get("transcript_status") == "completed"
            ):
                continue
            rows.append(
                {
                    "episode_id": ep["id"],
                    "show_id": ep["show_id"],
                    "title": ep["title"],
                    "audio_url": ep["audio_url"],
                    "duration_seconds": ep.get("duration_seconds"),
                    "published_at": ep.get("published_at"),
                }
            )
            kept += 1
        print(f"show {show_id}: {len(episodes)} 集，匯出 {kept} 集", file=sys.stderr)

    with args.out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    total_h = sum((r["duration_seconds"] or 0) for r in rows) / 3600
    print(
        f"episodes.jsonl 寫出 {len(rows)} 集、共 {total_h:.0f} 小時 → {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
