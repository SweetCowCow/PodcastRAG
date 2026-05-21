#!/usr/bin/env python3
"""Arm B: Vanilla RAG (fixed chunking + cosine top-k + LLM answer).

4-arm benchmark for docs/case-studies/rag-vs-long-context-2026-05-22.md.

Three idempotent stages (each caches output, re-run skips done work):
  1. dump   — fetch transcripts via backend API → .tmp/armb_transcripts.json
  2. embed  — chunk + embed → .tmp/armb_chunks.json + .tmp/armb_embeddings.npy
  3. eval   — per-question cosine top-k → gpt-4o → backend/eval/results/chat_eval_arm_b_2026-05-22.json

Env (NO secrets in argv):
  SESSION_COOKIE       (dump stage only)
  OPENAI_REAL_KEY      (embed stage — real OpenAI endpoint, AI Hub has no embedding)
  AIHUB_API_KEY        (eval stage — answer LLM, same provider as Arm C/D for fairness)
"""

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from typing import Any

import numpy as np
import tiktoken
from openai import OpenAI

SHOW_ID = "45fc2462-17cf-42f5-98a7-68fe1a222228"
BACKEND_URL = "https://podcastrag-api.zeabur.app"
ORIGIN = "https://app.podcastrag.app"
AIHUB_BASE = "https://hnd1.aihub.zeabur.ai/v1"
EMBED_MODEL = "text-embedding-3-small"
ANSWER_MODEL = "gpt-4o"
CHUNK_TOKENS = 512
CHUNK_OVERLAP = 50
TOP_K = 5

TMP = pathlib.Path(".tmp")
TMP.mkdir(exist_ok=True)
TRANSCRIPTS_CACHE = TMP / "armb_transcripts.json"
CHUNKS_CACHE = TMP / "armb_chunks.json"
EMBED_CACHE = TMP / "armb_embeddings.npy"


def _api_get(path: str, token: str) -> Any:
    req = urllib.request.Request(
        BACKEND_URL + path,
        headers={"Cookie": f"session_id={token}", "Origin": ORIGIN},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def stage_dump(token: str) -> None:
    if TRANSCRIPTS_CACHE.exists():
        print(f"[1/3 dump] cache hit {TRANSCRIPTS_CACHE} — skip")
        return
    print(f"[1/3 dump] listing episodes show={SHOW_ID}")
    payload = _api_get(f"/shows/{SHOW_ID}/episodes", token)
    eps = payload.get("episodes") if isinstance(payload, dict) else payload
    if not isinstance(eps, list):
        sys.exit(f"[dump] unexpected episodes payload shape: {type(payload)} keys={list(payload.keys()) if isinstance(payload,dict) else 'n/a'}")
    print(f"[1/3 dump] {len(eps)} episodes")
    out = []
    for i, ep in enumerate(eps):
        ep_id = ep.get("id") if isinstance(ep, dict) else ep
        title = ep.get("title", "") if isinstance(ep, dict) else ""
        try:
            tx = _api_get(f"/episodes/{ep_id}/transcript", token)
            segs = tx.get("segments", [])
            text = "\n".join(s.get("text", "") for s in segs)
            out.append({"episode_id": ep_id, "title": title, "text": text})
            print(f"  [{i+1}/{len(eps)}] {title[:40]} ({len(text)} chars)")
        except urllib.error.HTTPError as e:
            print(f"  [{i+1}/{len(eps)}] {title[:40]} → SKIP HTTP {e.code}")
    TRANSCRIPTS_CACHE.write_text(json.dumps(out, ensure_ascii=False))
    print(f"[1/3 dump] saved → {TRANSCRIPTS_CACHE} ({len(out)} non-empty)")


def _chunk(text: str, enc) -> list[str]:
    toks = enc.encode(text)
    out = []
    i = 0
    while i < len(toks):
        out.append(enc.decode(toks[i : i + CHUNK_TOKENS]))
        i += CHUNK_TOKENS - CHUNK_OVERLAP
    return out


def stage_embed(openai_key: str) -> None:
    if CHUNKS_CACHE.exists() and EMBED_CACHE.exists():
        print("[2/3 embed] cache hit — skip")
        return
    if not TRANSCRIPTS_CACHE.exists():
        sys.exit("[embed] need stage 1 first")
    transcripts = json.loads(TRANSCRIPTS_CACHE.read_text())
    enc = tiktoken.get_encoding("cl100k_base")
    chunks = []
    for tx in transcripts:
        for ch in _chunk(tx["text"], enc):
            if ch.strip():
                chunks.append({"episode_id": tx["episode_id"], "title": tx["title"], "text": ch})
    print(f"[2/3 embed] {len(chunks)} chunks from {len(transcripts)} episodes")
    CHUNKS_CACHE.write_text(json.dumps(chunks, ensure_ascii=False))

    client = OpenAI(api_key=openai_key)
    batch = 100
    embs = []
    for i in range(0, len(chunks), batch):
        sub = [c["text"] for c in chunks[i : i + batch]]
        resp = client.embeddings.create(model=EMBED_MODEL, input=sub)
        embs.extend([d.embedding for d in resp.data])
        print(f"  embedded {min(i + batch, len(chunks))}/{len(chunks)}")
    arr = np.array(embs, dtype=np.float32)
    np.save(EMBED_CACHE, arr)
    print(f"[2/3 embed] saved → {EMBED_CACHE} shape={arr.shape}")


def _cosine_topk(q: np.ndarray, embs: np.ndarray, k: int) -> list[int]:
    qn = q / (np.linalg.norm(q) + 1e-9)
    en = embs / (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    sims = en @ qn
    return np.argsort(-sims)[:k].tolist()


def _answer_match(answer: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    al = answer.lower()
    return sum(1 for kw in keywords if kw.lower() in al) / len(keywords)


def stage_eval(openai_key: str, aihub_key: str, dataset_path: str, out_path: str) -> None:
    chunks = json.loads(CHUNKS_CACHE.read_text())
    embs = np.load(EMBED_CACHE)
    ds = json.loads(pathlib.Path(dataset_path).read_text())
    items_in = ds["items"]
    embed_client = OpenAI(api_key=openai_key)
    chat_client = OpenAI(api_key=aihub_key, base_url=AIHUB_BASE)
    out_items = []
    print(f"[3/3 eval] {len(items_in)} questions")
    for i, item in enumerate(items_in):
        t0 = time.time()
        qemb_resp = embed_client.embeddings.create(model=EMBED_MODEL, input=[item["question"]])
        qemb = np.array(qemb_resp.data[0].embedding, dtype=np.float32)
        topk = _cosine_topk(qemb, embs, TOP_K)
        ctx = "\n\n".join(
            f"[{j+1}] ({chunks[idx]['title']}) {chunks[idx]['text']}"
            for j, idx in enumerate(topk)
        )
        prompt = (
            "你是 podcast 內容問答助手。以下是檢索到的段落，請只根據這些內容回答問題。"
            "如果內容沒提到，請說「資料中沒提到」。\n\n"
            f"{ctx}\n\n問題：{item['question']}\n回答："
        )
        chat = chat_client.chat.completions.create(
            model=ANSWER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        ans = chat.choices[0].message.content or ""
        top_eps = {chunks[idx]["episode_id"] for idx in topk}
        recall = 1.0 if item.get("source_episode_id") in top_eps else 0.0
        am = _answer_match(ans, item.get("expected_answer_keywords", []))
        out_items.append(
            {
                "id": item["id"],
                "type": item.get("type", ""),
                "recall_at_k": recall,
                "answer_match": round(am, 4),
                "answer": ans,
                "latency_ms": round((time.time() - t0) * 1000, 1),
            }
        )
        print(f"  [{i+1}/{len(items_in)}] {item['id']} recall={recall} am={round(am,2)}")
    agg = {
        "n": len(out_items),
        "n_scored_recall": len(out_items),
        "recall_at_k_mean": round(float(np.mean([x["recall_at_k"] for x in out_items])), 4),
        "answer_match_mean": round(float(np.mean([x["answer_match"] for x in out_items])), 4),
    }
    result = {
        "label": "arm-b-vanilla-rag",
        "dataset": dataset_path,
        "show_id": SHOW_ID,
        "top_k": TOP_K,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "aggregate": agg,
        "items": out_items,
    }
    pathlib.Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[3/3 eval] saved → {out_path}")
    print(
        f"Results [arm-b-vanilla-rag]:  Recall@5={agg['recall_at_k_mean']}  "
        f"answer_match={agg['answer_match_mean']}"
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["dump", "embed", "eval", "all"], default="all")
    p.add_argument("--dataset", default="backend/eval/datasets/this-not-that-cool.json")
    p.add_argument("--out", default="backend/eval/results/chat_eval_arm_b_2026-05-22.json")
    args = p.parse_args()

    token = os.environ.get("SESSION_COOKIE", "")
    openai_key = os.environ.get("OPENAI_REAL_KEY", "")
    aihub_key = os.environ.get("AIHUB_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if args.stage in ("dump", "all"):
        if not token:
            sys.exit("SESSION_COOKIE env required for dump stage")
        stage_dump(token)
    if args.stage in ("embed", "all"):
        if not openai_key:
            sys.exit("OPENAI_REAL_KEY env required for embed stage (AI Hub has no embedding)")
        stage_embed(openai_key)
    if args.stage in ("eval", "all"):
        if not openai_key:
            sys.exit("OPENAI_REAL_KEY env required (question embedding)")
        if not aihub_key:
            sys.exit("AIHUB_API_KEY env required (answer LLM)")
        stage_eval(openai_key, aihub_key, args.dataset, args.out)


if __name__ == "__main__":
    main()
