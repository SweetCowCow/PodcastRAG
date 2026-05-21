#!/usr/bin/env python3
"""Arm A: Long-context (entire source episode + ±2 neighbors → gpt-4o 128k).

4-arm benchmark Step 4. Reuses .tmp/armb_transcripts.json (Arm B dump cache).

Per question:
  - locate source_episode_id index in transcripts list (RSS order: newest→oldest)
  - take that episode + 2 before + 2 after (clamped) → ~5 episodes ≈ 27k tokens
  - prompt: 完整逐字稿 + 問題 → gpt-4o (AI Hub, same provider as Arm C/D)

Output schema matches chat_eval_*_2026-05-22.json.

Env (NO secrets in argv):
  AIHUB_API_KEY  (answer LLM via AI Hub)
"""

import argparse
import json
import os
import pathlib
import sys
import time

import tiktoken
from openai import OpenAI

SHOW_ID = "45fc2462-17cf-42f5-98a7-68fe1a222228"
AIHUB_BASE = "https://hnd1.aihub.zeabur.ai/v1"
ANSWER_MODEL = "gpt-4o"
NEIGHBOR_WINDOW = 2
MAX_CONTEXT_TOKENS = 110_000

TMP = pathlib.Path(".tmp")
TRANSCRIPTS_CACHE = TMP / "armb_transcripts.json"


def _truncate_tokens(text: str, enc, max_tok: int) -> str:
    toks = enc.encode(text)
    if len(toks) <= max_tok:
        return text
    return enc.decode(toks[:max_tok])


def stage_eval(api_key: str, dataset_path: str, out_path: str) -> None:
    if not TRANSCRIPTS_CACHE.exists():
        sys.exit(
            f"need {TRANSCRIPTS_CACHE} — run arm_b_vanilla_rag.py --stage dump first"
        )
    transcripts = json.loads(TRANSCRIPTS_CACHE.read_text())
    by_id = {tx["episode_id"]: i for i, tx in enumerate(transcripts)}
    print(f"[arm A] {len(transcripts)} transcripts in cache")

    ds = json.loads(pathlib.Path(dataset_path).read_text())
    items_in = ds["items"]
    client = OpenAI(api_key=api_key, base_url=AIHUB_BASE)
    enc = tiktoken.get_encoding("cl100k_base")
    out_items = []
    print(f"[arm A] {len(items_in)} questions")

    for i, item in enumerate(items_in):
        t0 = time.time()
        src_id = item.get("source_episode_id")
        idx = by_id.get(src_id)
        if idx is None:
            # cross-episode 題可能無 source — 用全 show 前 5 集
            window = transcripts[:5]
        else:
            lo = max(0, idx - NEIGHBOR_WINDOW)
            hi = min(len(transcripts), idx + NEIGHBOR_WINDOW + 1)
            window = transcripts[lo:hi]

        ctx_parts = [f"=== {tx['title']} ===\n{tx['text']}" for tx in window]
        ctx = "\n\n".join(ctx_parts)
        ctx = _truncate_tokens(ctx, enc, MAX_CONTEXT_TOKENS)

        prompt = (
            "以下是 podcast 節目的逐字稿。請只根據這些內容回答問題。"
            "如果內容沒提到，請說「資料中沒提到」。\n\n"
            f"{ctx}\n\n問題：{item['question']}\n回答："
        )
        try:
            chat = client.chat.completions.create(
                model=ANSWER_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            ans = chat.choices[0].message.content or ""
        except Exception as e:
            print(f"  [{i+1}/{len(items_in)}] {item['id']} ERROR: {e}")
            ans = f"[ERROR] {e}"

        top_eps = {tx["episode_id"] for tx in window}
        recall = 1.0 if src_id in top_eps else 0.0
        kws = item.get("expected_answer_keywords", [])
        am = 0.0
        if kws:
            al = ans.lower()
            am = sum(1 for k in kws if k.lower() in al) / len(kws)
        out_items.append(
            {
                "id": item["id"],
                "type": item.get("type", ""),
                "recall_at_k": recall,
                "answer_match": round(am, 4),
                "answer": ans,
                "latency_ms": round((time.time() - t0) * 1000, 1),
                "context_episodes": len(window),
                "context_tokens": len(enc.encode(ctx)),
            }
        )
        print(
            f"  [{i+1}/{len(items_in)}] {item['id']} "
            f"ctx={len(window)}ep/{out_items[-1]['context_tokens']}t recall={recall} am={round(am, 2)}"
        )

    import numpy as np

    agg = {
        "n": len(out_items),
        "n_scored_recall": len(out_items),
        "recall_at_k_mean": round(
            float(np.mean([x["recall_at_k"] for x in out_items])), 4
        ),
        "answer_match_mean": round(
            float(np.mean([x["answer_match"] for x in out_items])), 4
        ),
        "avg_context_tokens": round(
            float(np.mean([x["context_tokens"] for x in out_items])), 0
        ),
    }
    result = {
        "label": "arm-a-longcontext",
        "dataset": dataset_path,
        "show_id": SHOW_ID,
        "neighbor_window": NEIGHBOR_WINDOW,
        "model": ANSWER_MODEL,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "aggregate": agg,
        "items": out_items,
    }
    pathlib.Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[arm A] saved → {out_path}")
    print(
        f"Results [arm-a-longcontext]:  Recall@5={agg['recall_at_k_mean']}  "
        f"answer_match={agg['answer_match_mean']}  avg_ctx={agg['avg_context_tokens']}t"
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="backend/eval/datasets/this-not-that-cool.json")
    p.add_argument(
        "--out", default="backend/eval/results/chat_eval_arm_a_2026-05-22.json"
    )
    args = p.parse_args()
    key = os.environ.get("AIHUB_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit("AIHUB_API_KEY env required")
    stage_eval(key, args.dataset, args.out)


if __name__ == "__main__":
    main()
