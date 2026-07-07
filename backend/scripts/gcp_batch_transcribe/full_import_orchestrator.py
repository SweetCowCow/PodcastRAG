#!/usr/bin/env python3
"""6.1 全量分批匯入 orchestrator（本機 nohup 跑）。

每批呼叫 import_results.py --limit BATCH（每次 fresh e2e login，避開 15 min
session TTL），批間輪詢 prod 唯讀 DB 直到積壓降到門檻以下才送下一批：

- import backlog = manifest accepted 數 − 兩節目 transcripts completed 數
- summary backlog = 兩節目已完成 transcript 但 ai_summary_status in
  (pending, running) 的集數（summary/topic 是 priority 2，批間才有空檔消化）

安全閥：
- AI Hub 餘額每批檢查一次，低於 FLOOR_USD 立即停（預期下游總成本 $6~12，
  燒超過 ~$25 = 異常）
- manifest failed 累計超過 MAX_FAILED 停下來等人工
- 目錄放 STOP 檔（touch STOP）→ 當前批收尾後優雅停止

進度全在 import_manifest.jsonl，中斷後重跑本腳本即續傳。
結尾自動跑一輪 --retry-failed。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "results" / "out"
MANIFEST = HERE / "import_manifest.jsonl"
STOP_FILE = HERE / "STOP"
IMPORT_SCRIPT = HERE / "import_results.py"

BATCH_SIZE = 100
POLL_INTERVAL = 60  # 秒
IMPORT_BACKLOG_GATE = 10   # 批間 import backlog 須低於此值
SUMMARY_BACKLOG_GATE = 150  # 批間 summary backlog 須低於此值
FLOOR_USD = 61.0   # AI Hub 餘額低於此值急停（baseline 86.25 − 25 緩衝）
MAX_FAILED = 30
STALL_POLLS = 30   # 連續 N 次輪詢 backlog 無下降 → 判定卡住停下

SHOW_IDS = (
    "e71e4f2b-1763-4c06-8164-6e395e4abdaf",  # 塞掐 Side Chat
    "efee016d-9311-4e24-9a6d-c44e59e88862",  # 台灣通勤第一品牌
)


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def db_conn_args() -> tuple[list[str], dict]:
    """從 ~/.claude.json 取 podcastrag-pg 唯讀連線；密碼走 PGPASSWORD env 不進 argv。"""
    cfg = json.load(open(Path.home() / ".claude.json"))
    url = next(
        a for a in cfg["mcpServers"]["podcastrag-pg"]["args"]
        if a.startswith("postgres")
    )
    u = urlparse(url.replace("+asyncpg", ""))
    args = ["psql", "-h", u.hostname, "-p", str(u.port or 5432),
            "-U", unquote(u.username), "-d", u.path.lstrip("/"),
            "-t", "-A", "-q"]
    env = {"PGPASSWORD": unquote(u.password or "")}
    return args, env


PSQL_ARGS, PSQL_ENV = db_conn_args()


def db_scalar_row(sql: str) -> list[str]:
    import os
    r = subprocess.run(
        PSQL_ARGS + ["-c", sql], capture_output=True, text=True, timeout=60,
        env={**os.environ, **PSQL_ENV},
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()[:200]}")
    return r.stdout.strip().split("|")


def prod_counts() -> dict:
    ids = "','".join(SHOW_IDS)
    row = db_scalar_row(f"""
      SELECT
        count(t.id) FILTER (WHERE t.status='completed'),
        count(t.id) FILTER (WHERE t.status='failed'),
        count(e.id) FILTER (WHERE t.status='completed'
                            AND e.ai_summary_status IN ('pending','running')),
        count(e.id) FILTER (WHERE t.status='completed'
                            AND e.ai_summary_status='failed')
      FROM episodes e LEFT JOIN transcripts t ON t.episode_id = e.id
      WHERE e.show_id IN ('{ids}')
    """)
    return {
        "transcripts_completed": int(row[0]),
        "transcripts_failed": int(row[1]),
        "summary_backlog": int(row[2]),
        "summary_failed": int(row[3]),
    }


def manifest_stats() -> dict:
    accepted = failed = 0
    seen: dict[str, str] = {}
    if MANIFEST.exists():
        for line in MANIFEST.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                seen[e["episode_id"]] = e["status"]
    for st in seen.values():
        if st == "accepted":
            accepted += 1
        else:
            failed += 1
    total = len(list(RESULTS_DIR.glob("*.json")))
    return {"accepted": accepted, "failed": failed,
            "pending": total - len(seen), "total": total}


def aihub_balance_usd() -> float | None:
    try:
        r = subprocess.run(
            ["npx", "zeabur", "ai-hub", "status", "-i=false", "--json"],
            capture_output=True, text=True, timeout=120,
        )
        d = json.loads(r.stdout)
        b = d.get("Balance") or d.get("balance")
        return int(b) / 100000
    except Exception as ex:  # fail-open：查不到只記 log 不擋
        log(f"WARN AI Hub balance 查詢失敗（不擋批次）：{ex}")
        return None


def run_batch(limit: int) -> int:
    r = subprocess.run(
        [sys.executable, str(IMPORT_SCRIPT),
         "--results-dir", str(RESULTS_DIR), "--e2e-login",
         "--limit", str(limit)],
        cwd=HERE, timeout=3600,
    )
    return r.returncode


def wait_for_drain() -> bool:
    """輪詢到積壓低於門檻。回傳 False = 卡住（backlog 連續不降）。"""
    last_backlog = None
    stalls = 0
    while True:
        m = manifest_stats()
        c = prod_counts()
        backlog = m["accepted"] - c["transcripts_completed"]
        log(
            f"poll: import_backlog={backlog} summary_backlog={c['summary_backlog']} "
            f"t_completed={c['transcripts_completed']} t_failed={c['transcripts_failed']} "
            f"s_failed={c['summary_failed']} manifest(acc={m['accepted']} "
            f"fail={m['failed']} pend={m['pending']})"
        )
        if backlog <= IMPORT_BACKLOG_GATE and c["summary_backlog"] <= SUMMARY_BACKLOG_GATE:
            return True
        combined = backlog + c["summary_backlog"]
        if last_backlog is not None and combined >= last_backlog:
            stalls += 1
            if stalls >= STALL_POLLS:
                log(f"STALL：積壓連續 {STALL_POLLS} 次輪詢未下降，停下等人工")
                return False
        else:
            stalls = 0
        last_backlog = combined
        time.sleep(POLL_INTERVAL)


def main() -> int:
    log(f"=== 6.1 全量分批匯入開始 batch={BATCH_SIZE} ===")
    m = manifest_stats()
    log(f"初始：total={m['total']} accepted={m['accepted']} "
        f"failed={m['failed']} pending={m['pending']}")
    batch_no = 0
    while True:
        if STOP_FILE.exists():
            log("偵測到 STOP 檔，優雅停止")
            return 2
        m = manifest_stats()
        if m["pending"] <= 0:
            break
        if m["failed"] > MAX_FAILED:
            log(f"ABORT：manifest failed={m['failed']} > {MAX_FAILED}，停下等人工")
            return 1
        bal = aihub_balance_usd()
        if bal is not None:
            log(f"AI Hub balance = ${bal:.2f}")
            if bal < FLOOR_USD:
                log(f"ABORT：AI Hub 餘額 ${bal:.2f} < floor ${FLOOR_USD}，急停")
                return 1
        batch_no += 1
        log(f"--- 批次 {batch_no}（pending={m['pending']}，送 {min(BATCH_SIZE, m['pending'])} 集）---")
        rc = run_batch(BATCH_SIZE)
        if rc != 0:
            log(f"WARN 批次 {batch_no} import_results.py rc={rc}（failed 記在 manifest，續跑）")
        if not wait_for_drain():
            return 1
    # 收尾：failed 自動重試一輪
    m = manifest_stats()
    if m["failed"] > 0:
        log(f"--- retry-failed 一輪（failed={m['failed']}）---")
        subprocess.run(
            [sys.executable, str(IMPORT_SCRIPT),
             "--results-dir", str(RESULTS_DIR), "--e2e-login", "--retry-failed"],
            cwd=HERE, timeout=3600,
        )
        wait_for_drain()
    m = manifest_stats()
    c = prod_counts()
    bal = aihub_balance_usd()
    log(f"=== 完成：manifest acc={m['accepted']} fail={m['failed']} | "
        f"prod t_completed={c['transcripts_completed']} t_failed={c['transcripts_failed']} "
        f"summary_backlog={c['summary_backlog']} s_failed={c['summary_failed']} | "
        f"AI Hub ${bal if bal is not None else '?'} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
