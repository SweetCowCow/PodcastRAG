#!/usr/bin/env python3
"""GCP VM 上的批次轉錄跑器（external-transcript-bulk-import task 3.1）。

讀 episodes.jsonl（export_episode_list.py 產出），逐集：
  1. 從 audio_url 下載音檔（RSS enclosure，ingress 免費）
  2. faster-whisper large-v3-turbo 轉錄
     （condition_on_previous_text=False + VAD filter：E407 實測防
     「字幕提供」幻覺循環；language 預設 zh）
  3. 落盤 out/{episode_id}.json —— 形狀 = 匯入 endpoint payload
     {model, language, text, segments: [{start, end, text}]}
  4. append manifest.jsonl：{episode_id, status: done|failed,
     audio_seconds, elapsed_seconds, error}

可中斷續跑：重啟時跳過 manifest 已 done 的集數（spot 回收由 systemd
Restart=always 自動續跑）。全部完成 + --shutdown-when-done → 關機省錢。

本機冒煙（task 3.2）：--device cpu --compute-type int8 --model small 可在
Mac 無 GPU 驗證輸出 schema 與續跑邏輯。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

MODEL_NAME_DEFAULT = "large-v3-turbo"
DOWNLOAD_TIMEOUT = 300
DOWNLOAD_RETRIES = 3

# 簡體字元占比超過此值 → 整集跑 OpenCC s2twp 轉繁（2026-07-02 費用 gate
# 樣本實測：language=zh 不保證繁體，塞掐 E106 整集出簡體）。
SIMPLIFIED_RATIO_THRESHOLD = 0.02


def _to_traditional_if_needed(texts: list[str]) -> list[str] | None:
    """偵測簡體並整批轉繁（s2twp = 簡→繁 + 台灣慣用語）。

    回傳轉換後清單；若簡體占比低於門檻回 None（不動原文，避免
    s2twp 對本來就繁體的文字做多餘的詞彙替換）。
    """
    from opencc import OpenCC  # VM 上 pip install opencc

    s2t = OpenCC("s2t")
    joined = "".join(texts)
    han = [c for c in joined if "一" <= c <= "鿿"]
    if not han:
        return None
    converted = s2t.convert(joined)
    diff = sum(1 for a, b in zip(joined, converted) if a != b)
    if diff / max(len(han), 1) < SIMPLIFIED_RATIO_THRESHOLD:
        return None
    s2twp = OpenCC("s2twp")
    return [s2twp.convert(t) for t in texts]


def load_episodes(path: Path) -> list[dict]:
    episodes = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                episodes.append(json.loads(line))
    return episodes


def load_manifest(path: Path) -> dict[str, dict]:
    """episode_id → 最新一筆 manifest 紀錄（後寫的蓋前面的）。"""
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


def download_audio(url: str, dest: Path) -> None:
    last_err: Exception | None = None
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "podcastrag-batch/1.0"}
            )
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as r:
                dest.write_bytes(r.read())
            return
        except Exception as exc:  # noqa: BLE001 — 重試後才放棄
            last_err = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"download failed after {DOWNLOAD_RETRIES} tries: {last_err}")


def transcribe_one(model, audio_path: Path, language: str) -> dict:
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        # E407 pilot（2026-06-12）：兩者都開才壓得住長音檔的幻覺循環。
        condition_on_previous_text=False,
        vad_filter=True,
    )
    segments = []
    texts = []
    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue
        segments.append(
            {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": text}
        )
        texts.append(text)

    converted = _to_traditional_if_needed(texts)
    if converted is not None:
        print("  (偵測到簡體輸出 → OpenCC s2twp 轉繁)")
        texts = converted
        for seg_dict, new_text in zip(segments, texts):
            seg_dict["text"] = new_text

    return {
        "language": info.language or language,
        "text": "".join(texts),
        "segments": segments,
        "audio_seconds": round(info.duration or 0.0, 1),
    }


def print_progress(episodes: list[dict], manifest: dict[str, dict]) -> None:
    done = [e for e in manifest.values() if e["status"] == "done"]
    failed = [e for e in manifest.values() if e["status"] == "failed"]
    remaining = len(episodes) - len(done)
    audio_done = sum(e.get("audio_seconds") or 0 for e in done)
    elapsed = sum(e.get("elapsed_seconds") or 0 for e in done)
    rtf = (audio_done / elapsed) if elapsed else 0.0
    remaining_audio = sum(
        (ep.get("duration_seconds") or 0)
        for ep in episodes
        if ep["episode_id"] not in manifest
        or manifest[ep["episode_id"]]["status"] != "done"
    )
    eta_h = (remaining_audio / rtf / 3600) if rtf else float("inf")
    print(
        f"done={len(done)} failed={len(failed)} remaining={remaining} "
        f"audio_done={audio_done / 3600:.1f}h RTF={rtf:.1f}x "
        f"ETA≈{eta_h:.1f}h"
    )
    for e in failed:
        print(f"  FAILED {e['episode_id']}: {e.get('error', '')[:120]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=Path, default=Path("episodes.jsonl"))
    ap.add_argument("--workdir", type=Path, default=Path("."))
    ap.add_argument("--model", default=MODEL_NAME_DEFAULT)
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--language", default="zh")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 集（冒煙用）")
    ap.add_argument("--retry-failed", action="store_true",
                    help="重跑 manifest 內 failed 的集數")
    ap.add_argument("--progress", action="store_true",
                    help="只印 manifest 進度後離開")
    ap.add_argument("--shutdown-when-done", action="store_true")
    args = ap.parse_args()

    workdir = args.workdir.resolve()
    out_dir = workdir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = workdir / "manifest.jsonl"

    episodes = load_episodes(args.episodes)
    manifest = load_manifest(manifest_path)

    if args.progress:
        print_progress(episodes, manifest)
        return 0

    pending = [
        ep
        for ep in episodes
        if ep["episode_id"] not in manifest
        or (
            args.retry_failed
            and manifest[ep["episode_id"]]["status"] == "failed"
        )
    ]
    if args.limit:
        pending = pending[: args.limit]

    print(
        f"episodes={len(episodes)} done={len(manifest)} pending={len(pending)} "
        f"model={args.model} device={args.device}"
    )
    if not pending:
        print("nothing to do")
        if args.shutdown_when_done:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=False)
        return 0

    from faster_whisper import WhisperModel  # import 放這裡讓 --progress 不用裝

    model = WhisperModel(
        args.model, device=args.device, compute_type=args.compute_type
    )
    model_label = f"faster-whisper-{args.model}"

    for i, ep in enumerate(pending, 1):
        ep_id = ep["episode_id"]
        t0 = time.monotonic()
        print(f"[{i}/{len(pending)}] {ep_id} {ep.get('title', '')[:50]}")
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".mp3", dir=workdir, delete=True
            ) as tmp:
                download_audio(ep["audio_url"], Path(tmp.name))
                result = transcribe_one(model, Path(tmp.name), args.language)
            payload = {
                "model": model_label,
                "language": result["language"],
                "text": result["text"],
                "segments": result["segments"],
            }
            # 先寫 tmp 再 rename：殺在半路不會留半個 JSON
            out_path = out_dir / f"{ep_id}.json"
            tmp_path = out_dir / f"{ep_id}.json.tmp"
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            tmp_path.rename(out_path)
            append_manifest(
                manifest_path,
                {
                    "episode_id": ep_id,
                    "status": "done",
                    "audio_seconds": result["audio_seconds"],
                    "elapsed_seconds": round(time.monotonic() - t0, 1),
                    "error": None,
                },
            )
        except Exception as exc:  # noqa: BLE001 — 單集失敗不擋整批
            print(f"  FAILED: {exc}", file=sys.stderr)
            append_manifest(
                manifest_path,
                {
                    "episode_id": ep_id,
                    "status": "failed",
                    "audio_seconds": ep.get("duration_seconds"),
                    "elapsed_seconds": round(time.monotonic() - t0, 1),
                    "error": str(exc)[:500],
                },
            )

    manifest = load_manifest(manifest_path)
    print_progress(episodes, manifest)

    all_done = all(
        manifest.get(ep["episode_id"], {}).get("status") == "done"
        for ep in episodes
    )
    if args.shutdown_when_done and (all_done or not args.limit):
        # failed 集數留給 --retry-failed 或本機重跑；不因少數失敗掛機燒錢
        print("batch finished — shutting down")
        subprocess.run(["sudo", "shutdown", "-h", "now"], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
