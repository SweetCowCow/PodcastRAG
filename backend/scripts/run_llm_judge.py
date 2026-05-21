#!/usr/bin/env python3
"""LLM-as-judge: re-score 4 arms × 30 questions by answer text quality.

Why: existing `answer_match` (keyword substring) doesn't differentiate generation
strategies. Each arm scored 0/1 even when answers diverge semantically.
See feedback_eval_metric_arm_blindness.md.

Design:
  - Per question, present 4 arm answers + reference keywords + notes to gpt-4o
  - Judge scores each on 4 dimensions (0-1 each), then overall (0-1):
      grounding     (no hallucination beyond reference)
      completeness  (covers reference keywords semantically, not just substring)
      fluency       (readable, natural)
      refusal_aptness (negative-type: high score for honest "not mentioned")
  - Single call per question = 30 calls total, gpt-4o (AI Hub)
  - Saves: backend/eval/results/llm_judge_2026-05-22.json

Env:
  AIHUB_API_KEY
"""

import json
import os
import pathlib
import sys
import time
from typing import Any

import re

from openai import OpenAI


def _extract_json(raw: str) -> dict:
    """AI Hub gpt-4o wraps JSON in markdown code blocks despite response_format."""
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return json.loads(s)

AIHUB_BASE = "https://hnd1.aihub.zeabur.ai/v1"
JUDGE_MODEL = "gpt-4o"

ARM_FILES = {
    "A": "backend/eval/results/chat_eval_arm_a_2026-05-22.json",
    "B": "backend/eval/results/chat_eval_arm_b_2026-05-22.json",
    "C": "backend/eval/results/chat_eval_rule_based_2026-05-22.json",
    "D": "backend/eval/results/chat_eval_agentic_2026-05-22.json",
}
ARM_LABELS = {
    "A": "long-context",
    "B": "vanilla-rag",
    "C": "rule-based",
    "D": "agentic",
}
DATASET = "backend/eval/datasets/this-not-that-cool.json"
OUT = "backend/eval/results/llm_judge_2026-05-22.json"

JUDGE_PROMPT_TMPL = """你是 RAG 系統的使用者體驗評審。下面是同一個問題的 4 個系統答案。請從**使用者拿到的價值**角度評分。

問題類型：{qtype}
使用者問題：{question}
正確答案的關鍵詞（語意覆蓋而非字面 match）：{keywords}
專家筆記（節目實際內容、判斷答案是否正確的 ground truth）：{notes}

四個系統的答案：
[A long-context] {ans_a}

[B vanilla-rag] {ans_b}

[C rule-based] {ans_c}

[D agentic] {ans_d}

對 A、B、C、D 各給 4 維度 0-1 評分 + 最後 overall（0-1）：

- grounding：答案是否跟「專家筆記」一致，沒幻覺出筆記沒提到的事實。0=嚴重編造、1=完全 grounded
- completeness：使用者拿到問題的答案了嗎？看「答案是否語意覆蓋關鍵詞所代表的要點」。0=完全沒回到、1=全部覆蓋
- fluency：流暢、邏輯清楚。0=錯亂、1=自然
- refusal_aptness：**只對 negative 類型題適用**（節目本來就沒提的陷阱題）。在 negative 題禮貌拒答 + 沒幻覺 = 1.0；其他類型題此維度 = null
- overall：綜合分數 0-1

**重要 rubric**：
- 非 negative 題：使用者期待拿到答案 → 答「資料中沒提到 / 我不知道 / 技術問題」這類拒答 = overall **0.0-0.2**（系統失敗）
- negative 題：使用者問陷阱題（節目沒提）→ 禮貌拒答 = overall **0.9-1.0**；幻覺編造 = **0.0**
- 一般評分站在使用者立場，不站在「RAG 系統 chunk 限制」立場

只回 JSON，schema：
{{"A": {{"grounding": float, "completeness": float, "fluency": float, "refusal_aptness": float|null, "overall": float, "note": "一句話評語"}}, "B": ..., "C": ..., "D": ...}}
"""


def _load_arms() -> dict[str, dict[str, Any]]:
    out = {}
    for k, p in ARM_FILES.items():
        data = json.loads(pathlib.Path(p).read_text())
        out[k] = {it["id"]: it for it in data["items"]}
    return out


def _truncate(s: str, n: int = 800) -> str:
    return s if len(s) <= n else s[:n] + "…[truncated]"


def main() -> None:
    key = os.environ.get("AIHUB_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit("AIHUB_API_KEY env required")
    client = OpenAI(api_key=key, base_url=AIHUB_BASE)

    ds = json.loads(pathlib.Path(DATASET).read_text())
    arms = _load_arms()
    out_items = []
    print(f"[judge] {len(ds['items'])} questions × 4 arms = {len(ds['items'])} judge calls")

    for i, item in enumerate(ds["items"]):
        qid = item["id"]
        t0 = time.time()
        prompt = JUDGE_PROMPT_TMPL.format(
            qtype=item.get("type", ""),
            question=item["question"],
            keywords=", ".join(item.get("expected_answer_keywords", [])),
            notes=item.get("notes", "")[:400],
            ans_a=_truncate(arms["A"].get(qid, {}).get("answer", "")),
            ans_b=_truncate(arms["B"].get(qid, {}).get("answer", "")),
            ans_c=_truncate(arms["C"].get(qid, {}).get("answer", "")),
            ans_d=_truncate(arms["D"].get(qid, {}).get("answer", "")),
        )
        try:
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                response_format={"type": "json_object"},
            )
            scores = _extract_json(resp.choices[0].message.content or "{}")
        except Exception as e:
            print(f"  [{i+1}/{len(ds['items'])}] {qid} JUDGE ERROR: {e}")
            scores = {}
        out_items.append(
            {
                "id": qid,
                "type": item.get("type", ""),
                "question": item["question"],
                "scores": scores,
                "judge_latency_ms": round((time.time() - t0) * 1000, 1),
            }
        )
        if scores:
            ovr = {k: round(scores.get(k, {}).get("overall", 0), 2) for k in "ABCD"}
            print(f"  [{i+1}/{len(ds['items'])}] {qid} overall A/B/C/D = {ovr['A']}/{ovr['B']}/{ovr['C']}/{ovr['D']}")
        else:
            print(f"  [{i+1}/{len(ds['items'])}] {qid} (no scores)")

    # Aggregate
    import numpy as np

    agg: dict[str, dict[str, float]] = {}
    for arm in "ABCD":
        arm_scores: dict[str, list[float]] = {
            "grounding": [],
            "completeness": [],
            "fluency": [],
            "refusal_aptness": [],
            "overall": [],
        }
        for it in out_items:
            s = it.get("scores", {}).get(arm, {})
            for dim in arm_scores:
                v = s.get(dim)
                if isinstance(v, (int, float)):
                    arm_scores[dim].append(float(v))
        agg[ARM_LABELS[arm]] = {
            dim: round(float(np.mean(v)), 4) if v else None
            for dim, v in arm_scores.items()
        }

    result = {
        "judge_model": JUDGE_MODEL,
        "dataset": DATASET,
        "n_questions": len(out_items),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "aggregate": agg,
        "items": out_items,
    }
    pathlib.Path(OUT).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[judge] saved → {OUT}")
    print("\n=== Aggregate by arm ===")
    print(f"{'arm':<14} {'grounding':<11} {'complete':<11} {'fluency':<10} {'refusal':<10} {'OVERALL':<10}")
    for arm in "ABCD":
        a = agg[ARM_LABELS[arm]]
        print(
            f"{ARM_LABELS[arm]:<14} {a.get('grounding') or '-':<11} {a.get('completeness') or '-':<11} "
            f"{a.get('fluency') or '-':<10} {a.get('refusal_aptness') or '-':<10} {a.get('overall') or '-':<10}"
        )


if __name__ == "__main__":
    main()
