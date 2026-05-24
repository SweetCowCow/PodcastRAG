"""Classify root cause of hallucination for every severe / mild turn.

Reads a chat eval result + matching LLM-judge result + dataset, then asks
gpt-4o (via Zeabur AI Hub) to label each turn whose hallucination_severity
is severe or mild with one of:

    tool_call_empty       — agent issued no tool calls (or all failed) and answered from prior knowledge
    noise_induced         — tools returned topic-related chunks that did NOT contain the answer; agent fabricated
    wrong_tool_chosen     — agent invoked a tool but with wrong name/args, missing data it should have retrieved
    tool_returned_partial — tool returned partial correct data; agent fabricated the missing fields

Each classified turn also carries a one-line `evidence` string referencing
tool_calls_made / recall_at_k / answer content.

Output JSON:

    {
      "meta": {
        "judge_model": "gpt-4o",
        "dataset_file": "...",
        "eval_file": "...",
        "judge_file": "...",
        "classifier_model": "gpt-4o",
        "run_at": "2026-05-24T..."
      },
      "turns": [
        {"item_id": "b01", "turn_index": 1, "severity": "severe",
         "root_cause": "tool_call_empty", "evidence": "..."},
        ...
      ],
      "summary": {
        "n_classified": 20,
        "severity_x_root_cause": {
          "severe": {"tool_call_empty": 5, "noise_induced": 3, ...},
          "mild":   {...}
        }
      }
    }

Exit non-zero (without overwriting the output file) when any turn comes
back with root_cause = null or an out-of-enum value.

Usage:
    python -m backend.eval.scripts.classify_hallucination_root_cause \
        --eval-file backend/eval/results/chat_eval_grounding_and_ordinal.json \
        --judge-file backend/eval/results/llm_judge_grounding_and_ordinal.json \
        --dataset-file backend/eval/datasets/extended-multi-turn-40.json \
        --out backend/eval/results/hallucination_root_cause_distribution.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

CLASSIFIER_MODEL = "gpt-4o"
HUB_BASE_URL = "https://hnd1.aihub.zeabur.ai/v1"
ROOT_CAUSE_ENUM = {
    "tool_call_empty",
    "noise_induced",
    "wrong_tool_chosen",
    "tool_returned_partial",
}

CLASSIFIER_INSTRUCTION = """你是 PodcastRAG eval pipeline 的 root-cause 分類員。

針對一筆 chat agent turn 的 hallucination，從以下 4 個 root_cause 選 1 個：

- tool_call_empty       : agent 完全沒呼 tool（tool_calls_made == '[]'）或呼的 tool 全部失敗，最後直接憑印象答 → 編造
- noise_induced         : agent 有呼 tool 且 tool 有回 chunk，但 chunk 裡不含問題答案；agent 從這些 noise 段落「推論」編造一個看似合理的答案
- wrong_tool_chosen     : agent 呼了 tool 但 tool 名稱或參數選錯（譬如該用 find_episodes_by_guest 卻用 search_across_episodes，或關鍵字打錯）→ 沒拿到該拿的資料
- tool_returned_partial : tool 回了「部分正確」的資料（譬如有 EP 但缺集數標題），agent 把缺失欄位編造補齊

判斷訊號：
- tool_calls_made == '[]'  → tool_call_empty
- tool_calls_made 非空 + recall_at_k == 0 + tool_required_hit == 0 → 多半 wrong_tool_chosen 或 noise_induced
- tool_calls_made 非空 + recall_at_k > 0  → noise_induced（chunk 有 retrieve 到但 LLM 編造）或 tool_returned_partial
- judge reasoning 提到「編造節目名稱 / 不存在」→ 配合 tool_calls_made 判 tool_call_empty 或 wrong_tool_chosen
- judge reasoning 提到「描述中並未明確 / 部分覆蓋」→ 偏 noise_induced 或 tool_returned_partial

回傳純 JSON（不要 markdown code fence）：
{"root_cause": "<enum>", "evidence": "<一句話 ≤80 字，引用 tool_calls_made / recall_at_k / answer 或 reasoning 內容>"}"""


def _strip_code_fence(text: str) -> str:
    """AI Hub 的 gpt-4o 仍會包 ```json``` 即使 response_format=json_object。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _question_lookup(dataset: dict) -> dict[tuple[str, int], dict]:
    """Map (item_id, turn_index) -> {question, expected_keywords, expected_tools}."""
    out: dict[tuple[str, int], dict] = {}
    for item in dataset.get("items", []):
        item_id = item["id"]
        for idx, turn in enumerate(item.get("turns", []), start=1):
            out[(item_id, idx)] = {
                "question": turn.get("question", ""),
                "expected_answer_keywords": turn.get("expected_answer_keywords", []),
                "expected_tool_calls_required": turn.get("expected_tool_calls_required", []),
                "expected_tool_calls_acceptable": turn.get("expected_tool_calls_acceptable", []),
            }
    return out


def _eval_turn_lookup(eval_data: dict) -> dict[tuple[str, int], dict]:
    out: dict[tuple[str, int], dict] = {}
    for t in eval_data.get("turns", []):
        out[(t["item_id"], int(t["turn_index"]))] = t
    return out


def _build_classifier_input(judge_turn: dict, eval_turn: dict, dataset_turn: dict) -> str:
    return json.dumps(
        {
            "item_id": judge_turn["item_id"],
            "turn_index": judge_turn["turn_index"],
            "design_type": judge_turn.get("design_type"),
            "severity": judge_turn["hallucination_severity"],
            "question": dataset_turn.get("question", ""),
            "expected_answer_keywords": dataset_turn.get("expected_answer_keywords", []),
            "expected_tool_calls_required": dataset_turn.get("expected_tool_calls_required", []),
            "tool_calls_made": eval_turn.get("tool_calls_made", "[]"),
            "tool_required_hit": eval_turn.get("tool_required_hit"),
            "tool_acceptable_hit": eval_turn.get("tool_acceptable_hit"),
            "recall_at_k": eval_turn.get("recall_at_k"),
            "answer": eval_turn.get("answer", "")[:800],
            "judge_reasoning": judge_turn.get("reasoning", ""),
        },
        ensure_ascii=False,
        indent=2,
    )


def classify_one(client: OpenAI, payload: str) -> dict:
    resp = client.chat.completions.create(
        model=CLASSIFIER_MODEL,
        messages=[
            {"role": "system", "content": CLASSIFIER_INSTRUCTION},
            {"role": "user", "content": payload},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or ""
    cleaned = _strip_code_fence(raw)
    return json.loads(cleaned)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-file", required=True, type=Path)
    parser.add_argument("--judge-file", required=True, type=Path)
    parser.add_argument("--dataset-file", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    eval_data = json.loads(args.eval_file.read_text(encoding="utf-8"))
    judge_data = json.loads(args.judge_file.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset_file.read_text(encoding="utf-8"))

    judge_model_in_input = judge_data.get("judge_model")
    questions = _question_lookup(dataset)
    eval_turns = _eval_turn_lookup(eval_data)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY env var not set (this is the AI Hub key)", file=sys.stderr)
        return 2
    client = OpenAI(api_key=api_key, base_url=HUB_BASE_URL)

    classified: list[dict] = []
    invalid: list[dict] = []

    targets = [
        t for t in judge_data.get("turns", [])
        if t.get("hallucination_severity") in ("severe", "mild")
    ]
    print(f"Classifying {len(targets)} turns (severe + mild) with {CLASSIFIER_MODEL}…", file=sys.stderr)

    for judge_turn in targets:
        key = (judge_turn["item_id"], int(judge_turn["turn_index"]))
        eval_turn = eval_turns.get(key, {})
        dataset_turn = questions.get(key, {})
        payload = _build_classifier_input(judge_turn, eval_turn, dataset_turn)
        try:
            result = classify_one(client, payload)
        except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
            invalid.append({"key": key, "error": f"{type(exc).__name__}: {exc}"})
            continue

        root_cause = result.get("root_cause")
        evidence = result.get("evidence")
        if root_cause not in ROOT_CAUSE_ENUM or not evidence:
            invalid.append({"key": key, "result": result})
            continue

        classified.append(
            {
                "item_id": judge_turn["item_id"],
                "turn_index": judge_turn["turn_index"],
                "severity": judge_turn["hallucination_severity"],
                "root_cause": root_cause,
                "evidence": evidence,
            }
        )
        print(f"  ✓ {judge_turn['item_id']} t{judge_turn['turn_index']} [{judge_turn['hallucination_severity']:>6}] → {root_cause}", file=sys.stderr)

    if invalid:
        print(f"ERROR: {len(invalid)} turn(s) classified with null/out-of-enum value or LLM error", file=sys.stderr)
        for inv in invalid:
            print(f"  - {inv}", file=sys.stderr)
        print("Output file NOT overwritten.", file=sys.stderr)
        return 1

    crosstab: dict[str, Counter] = defaultdict(Counter)
    for c in classified:
        crosstab[c["severity"]][c["root_cause"]] += 1

    severity_x_root_cause = {
        sev: {rc: crosstab[sev].get(rc, 0) for rc in sorted(ROOT_CAUSE_ENUM)}
        for sev in ("severe", "mild")
    }

    out_doc = {
        "meta": {
            "judge_model": judge_model_in_input,
            "dataset_file": str(args.dataset_file),
            "eval_file": str(args.eval_file),
            "judge_file": str(args.judge_file),
            "classifier_model": CLASSIFIER_MODEL,
            "run_at": datetime.now(timezone.utc).isoformat(),
        },
        "turns": classified,
        "summary": {
            "n_classified": len(classified),
            "severity_x_root_cause": severity_x_root_cause,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("== severity × root_cause ==")
    header = f"{'severity':<8}" + "".join(f"{rc:>22}" for rc in sorted(ROOT_CAUSE_ENUM)) + f"{'total':>8}"
    print(header)
    for sev in ("severe", "mild"):
        row = severity_x_root_cause[sev]
        total = sum(row.values())
        line = f"{sev:<8}" + "".join(f"{row[rc]:>22}" for rc in sorted(ROOT_CAUSE_ENUM)) + f"{total:>8}"
        print(line)
    print(f"\nWrote {args.out} ({len(classified)} turns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
