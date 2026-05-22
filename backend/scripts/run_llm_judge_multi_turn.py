#!/usr/bin/env python3
"""LLM-as-judge for the nested multi-turn-40 eval result.

Scores each turn on:
  - answer_quality (0-1)         : 對問題的整體回應品質（語意覆蓋 + 流暢 + 對使用者有用）
  - hallucination_severity       : "none" / "mild" / "severe"
  - context_carry_hit (0/1/null) : 多輪題 turn>=2 才量，看是否正確利用先前 context（ordinal、anaphora、follow-up）

Single-arm scoring (Arm D agentic, multi-turn-40 dataset).

Usage:
  python3 backend/scripts/run_llm_judge_multi_turn.py \\
      --eval backend/eval/results/chat_eval_agentic_multi_turn_40_2026-05-22.json \\
      --dataset backend/eval/datasets/extended-multi-turn-40.json \\
      --out backend/eval/results/llm_judge_multi_turn_40_2026-05-22.json

Env: AIHUB_API_KEY (or OPENAI_API_KEY, both work — 本機 OPENAI_API_KEY 實為 aihub key)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from statistics import mean

from openai import OpenAI

AIHUB_BASE = "https://hnd1.aihub.zeabur.ai/v1"
JUDGE_MODEL = "gpt-4o"


def _extract_json(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return json.loads(s)


PROMPT_TMPL = """你是 RAG 對話系統的評審。下面是一個對話 turn，請從**使用者拿到的價值**角度評分。

問題：{question}
期待答案的關鍵詞（語意覆蓋而非字面 match）：{keywords}
{multi_turn_block}
系統回的答案：
{answer}

請回以下 JSON（嚴格依結構，不要加額外鍵）：
{{
  "answer_quality": <0.0-1.0 數字，整體回應品質>,
  "hallucination_severity": "<none | mild | severe>",
  "context_carry_hit": <0 或 1 或 null；null 代表這個 turn 不適用 context carry 評量>,
  "reasoning": "<一句話講為什麼這樣評>"
}}

評分準則：
- answer_quality：0=完全沒回答到或胡謅；0.5=部分覆蓋；1.0=完整且 grounded
- hallucination_severity：
  - none = 無編造
  - mild = 小細節有點偏但不影響整體
  - severe = 編造節目沒提的人事物（譬如編造 episode title / 編造引用）
- context_carry_hit：
  - 對「Multi-turn 且 turn>=2」題目才量。turn 1 一律 null
  - 1 = 正確 resolve 上文 reference（譬如 t1 列舉 X,Y,Z，t2 問「第三個」回 Z）
  - 0 = 沒接住 reference（譬如把「第三集」當「EP3」literal 找）
  - null = 不適用（單輪題）
"""


def _judge_turn(
    client: OpenAI,
    turn: dict,
    turn_meta: dict,
    multi_turn_history: list[str] | None,
) -> dict:
    if multi_turn_history:
        mt_block = (
            "\n這是 multi-turn 對話的 turn "
            + str(turn["turn_index"])
            + "；先前 turn 的 (question -> answer head) 如下：\n"
            + "\n".join(f"  - {h}" for h in multi_turn_history)
            + "\n"
        )
    else:
        mt_block = ""
    prompt = PROMPT_TMPL.format(
        question=turn_meta["question"],
        keywords=turn_meta.get("expected_answer_keywords", []),
        multi_turn_block=mt_block,
        answer=turn["answer"] or "(空答案)",
    )
    resp = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": "你是嚴謹的 RAG 對話評審，回 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or "{}"
    return _extract_json(raw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    key = os.environ.get("AIHUB_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit("AIHUB_API_KEY env required")
    client = OpenAI(api_key=key, base_url=AIHUB_BASE)

    eval_data = json.loads(Path(args.eval).read_text())
    dataset = json.loads(Path(args.dataset).read_text())

    # Build (item_id, turn_index) → turn metadata lookup
    meta: dict[tuple[str, int], dict] = {}
    for it in dataset["items"]:
        for i, t in enumerate(it["turns"], 1):
            meta[(it["id"], i)] = t

    # Group eval turns by item for multi-turn history reconstruction
    by_item: dict[str, list[dict]] = {}
    for t in eval_data["turns"]:
        by_item.setdefault(t["item_id"], []).append(t)
    for ts in by_item.values():
        ts.sort(key=lambda x: x["turn_index"])

    scored: list[dict] = []
    n_turns = len(eval_data["turns"])
    done = 0
    for item_id, item_turns in by_item.items():
        history: list[str] = []
        for t in item_turns:
            done += 1
            key_meta = (item_id, t["turn_index"])
            turn_meta = meta.get(key_meta)
            if not turn_meta:
                continue
            print(f"  [{done:02d}/{n_turns}] {item_id} t{t['turn_index']}", flush=True)
            try:
                j = _judge_turn(client, t, turn_meta, history if t["is_multi_turn"] else None)
            except Exception as exc:
                print(f"    ! judge failed: {exc}", file=sys.stderr)
                j = {
                    "answer_quality": None,
                    "hallucination_severity": None,
                    "context_carry_hit": None,
                    "reasoning": f"judge_failed: {exc}",
                }
            scored.append({
                "item_id": item_id,
                "turn_index": t["turn_index"],
                "is_multi_turn": t["is_multi_turn"],
                "design_type": t["design_type"],
                "answer_quality": j.get("answer_quality"),
                "hallucination_severity": j.get("hallucination_severity"),
                "context_carry_hit": j.get("context_carry_hit"),
                "reasoning": j.get("reasoning", ""),
            })
            history.append(f"{turn_meta['question']} -> {(t['answer'] or '')[:80]}")
            time.sleep(0.2)  # gentle rate limit

    # Aggregate
    aq_vals = [s["answer_quality"] for s in scored if isinstance(s["answer_quality"], (int, float))]
    severe_count = sum(1 for s in scored if s["hallucination_severity"] == "severe")
    mild_count = sum(1 for s in scored if s["hallucination_severity"] == "mild")
    cc_vals = [s["context_carry_hit"] for s in scored if isinstance(s["context_carry_hit"], (int, float))]
    cc_hits = sum(1 for v in cc_vals if v >= 1)

    summary = {
        "n_turns_scored": len(scored),
        "answer_quality_mean": round(mean(aq_vals), 4) if aq_vals else None,
        "hallucination_severe_count": severe_count,
        "hallucination_mild_count": mild_count,
        "context_carry_total": len(cc_vals),
        "context_carry_hits": cc_hits,
        "context_carry_hit_rate": round(cc_hits / len(cc_vals), 4) if cc_vals else None,
    }

    out = {
        "eval_file": args.eval,
        "dataset_file": args.dataset,
        "judge_model": JUDGE_MODEL,
        "summary": summary,
        "turns": scored,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nWritten: {args.out}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
