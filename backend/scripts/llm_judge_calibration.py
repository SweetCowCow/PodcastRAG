#!/usr/bin/env python3
"""Calibrate LLM-as-judge against human-scored mini set (40 questions).

Goal: verify our judge prompt + model give scores that correlate with human
1-5 ratings on `_judge_minisset.json` BEFORE using it to score 4-arm × 30.

Output:
  - Pearson + Spearman correlation
  - Bucket accuracy (low/mid/high)
  - Per-question diff sorted by abs error
  - Pass if Pearson ≥ 0.7

Env: AIHUB_API_KEY
"""

import json
import os
import pathlib
import sys
import time

import re

from openai import OpenAI


def _extract_json(raw: str) -> dict:
    """AI Hub gpt-4o ignores response_format and wraps JSON in markdown code blocks.
    Strip the wrapper, then parse."""
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return json.loads(s)

AIHUB_BASE = "https://hnd1.aihub.zeabur.ai/v1"
JUDGE_MODEL = "gpt-4o"
DATASET = "backend/eval/datasets/_judge_minisset.json"
OUT = "backend/eval/results/llm_judge_calibration_2026-05-22.json"

JUDGE_PROMPT_TMPL = """你是 RAG 系統的使用者體驗評審。下面是一個 RAG 系統對使用者問題的答案。請從「使用者拿到的價值」角度評分。

使用者問題：{question}

檢索到的段落：
{chunks}

系統答案：
{answer}

請依以下標準評 overall 0-1 分（一個分數）：
- 1.0 = 使用者完整拿到問題的答案，內容正確、流暢
- 0.7-0.9 = 大致回答到、但有小遺漏或不完美
- 0.4-0.6 = 部分回答到 / 答了周邊資訊但沒命中核心
- 0.1-0.3 = 答非所問 / 大量缺漏 / 措辭混亂
- 0.0 = 嚴重幻覺 / 完全沒回答 / 答「我不知道」「資料中沒提到」這類拒答

**重要**：站在使用者立場，而不是站在 RAG 系統立場。即使檢索段落本身不足、系統「禮貌承認資訊不足」— 從使用者角度看，他**沒拿到答案**，這是失敗（low score 0.0-0.2），不是成功。

判斷重點：
1. 使用者問了什麼，答案實際回了多少（覆蓋度）
2. 內容是否正確（沒幻覺、跟段落一致）
3. 語言流暢、邏輯清楚

只回 JSON：{{"overall": float, "reasoning": "一句話"}}
"""


def main() -> None:
    key = os.environ.get("AIHUB_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit("AIHUB_API_KEY env required")
    client = OpenAI(api_key=key, base_url=AIHUB_BASE)

    ds = json.loads(pathlib.Path(DATASET).read_text())
    items = ds["items"]
    print(f"[calib] {len(items)} questions × judge model {JUDGE_MODEL}")

    results = []
    for i, item in enumerate(items):
        t0 = time.time()
        chunks_text = "\n\n".join(f"[{j+1}] {c}" for j, c in enumerate(item.get("chunks", [])))
        prompt = JUDGE_PROMPT_TMPL.format(
            question=item["question"],
            chunks=chunks_text,
            answer=item["answer"],
        )
        try:
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw = _extract_json(resp.choices[0].message.content or "{}")
            judge_score = float(raw.get("overall", -1))
            reasoning = raw.get("reasoning", "")
        except Exception as e:
            print(f"  [{i+1}/{len(items)}] {item['id']} ERROR: {e}")
            judge_score = -1.0
            reasoning = f"[error] {e}"

        human_norm = (item["human_score"] - 1) / 4.0  # 1-5 → 0-1
        results.append(
            {
                "id": item["id"],
                "question": item["question"][:80],
                "human_score": item["human_score"],
                "human_norm": round(human_norm, 4),
                "judge_score": round(judge_score, 4),
                "abs_error": round(abs(judge_score - human_norm), 4) if judge_score >= 0 else None,
                "reasoning": reasoning,
                "latency_ms": round((time.time() - t0) * 1000, 1),
            }
        )
        print(
            f"  [{i+1}/{len(items)}] {item['id']} human={item['human_score']} "
            f"→ judge={round(judge_score, 2)} (err={round(abs(judge_score - human_norm), 2)})"
        )

    # ── Correlations + bucket accuracy ────────────────────────────────
    import numpy as np

    valid = [r for r in results if r["judge_score"] >= 0]
    h = np.array([r["human_norm"] for r in valid])
    j = np.array([r["judge_score"] for r in valid])

    # Pearson (manual to avoid scipy dep)
    pearson = float(np.corrcoef(h, j)[0, 1])

    # Spearman via rank
    def _rank(a):
        order = np.argsort(a)
        ranks = np.empty_like(order, dtype=float)
        ranks[order] = np.arange(len(a))
        return ranks

    spearman = float(np.corrcoef(_rank(h), _rank(j))[0, 1])

    # Bucket: low (<0.4), mid (0.4-0.7), high (>=0.7)
    def _bucket(x):
        return "low" if x < 0.4 else ("mid" if x < 0.7 else "high")

    bucket_match = sum(1 for r in valid if _bucket(r["human_norm"]) == _bucket(r["judge_score"]))
    bucket_acc = bucket_match / len(valid) if valid else 0

    mae = float(np.mean([r["abs_error"] for r in valid]))

    pass_pearson = pearson >= 0.7
    pass_spearman = spearman >= 0.7
    overall_pass = pass_pearson and pass_spearman

    summary = {
        "judge_model": JUDGE_MODEL,
        "dataset": DATASET,
        "n_questions": len(items),
        "n_valid": len(valid),
        "pearson": round(pearson, 4),
        "spearman": round(spearman, 4),
        "mae": round(mae, 4),
        "bucket_accuracy": round(bucket_acc, 4),
        "pass_threshold_pearson_0.7": pass_pearson,
        "pass_threshold_spearman_0.7": pass_spearman,
        "overall_pass": overall_pass,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Top-5 worst errors
    worst = sorted([r for r in valid if r["abs_error"] is not None], key=lambda r: -r["abs_error"])[:5]

    result = {**summary, "worst_errors": worst, "items": results}
    pathlib.Path(OUT).write_text(json.dumps(result, ensure_ascii=False, indent=2))

    print(f"\n[calib] saved → {OUT}")
    print("\n=== Calibration summary ===")
    print(f"  Pearson  ρ = {round(pearson, 4)}  {'PASS' if pass_pearson else 'FAIL'} (threshold 0.7)")
    print(f"  Spearman ρ = {round(spearman, 4)}  {'PASS' if pass_spearman else 'FAIL'} (threshold 0.7)")
    print(f"  MAE        = {round(mae, 4)}")
    print(f"  Bucket acc = {round(bucket_acc, 4)} (low/mid/high agreement)")
    print(f"\n  Overall: {'PASS — judge approved to score 4-arm' if overall_pass else 'FAIL — tune prompt or change model'}")

    print("\n=== Top 5 worst errors ===")
    for r in worst:
        print(f"  {r['id']} human={r['human_score']}({r['human_norm']}) judge={r['judge_score']} err={r['abs_error']}")
        print(f"    Q: {r['question']}")
        print(f"    reasoning: {r['reasoning'][:120]}")


if __name__ == "__main__":
    main()
