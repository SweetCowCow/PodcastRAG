"""Derive `expected_behavior` + `expected_answer_summary` for the judge mini-set.

The production judge (`judge_chat_v2`) reads `expected_answer_summary` and
`expected_behavior` to decide whether a question should have been answered or
refused. `_judge_minisset.json` predates that contract and has zero question
overlap with any field-bearing golden set (verified 0/40), so the two fields
are derived from each item's own recorded `answer` + `human_score` in
deterministic tiers (change `r1-3-j-judge-harness-align`):

- non-refusal & human_score >= 4 -> expected_behavior "answer",
  summary seeded from the recorded answer (trustworthy: a human rated it 4-5).
- refusal-shaped & human_score >= 4 -> expected_behavior "refuse",
  summary = short 資料中確無此資訊 note (faithful refusal).
- everything with human_score <= 3 -> review queue: the recorded answer cannot
  seed a correct expected answer (wrongly refused, or answered wrong), so
  expected_answer_summary = literal "PENDING AUDIT" sentinel and
  expected_behavior is left for per-item human confirmation — never fabricated.

Refusal-shaped detection: a fixed pattern over the FIRST SENTENCE of the
answer (covering 沒提到 / 未提及 / 無法回答 / 我不知道 / 找不到 / 沒有足夠資訊 類).
First-sentence scope matters: 4 items substantively answer and only append a
「細節未詳細提及」-style hedge in a later sentence — those are answers, not
refusals. Answers wrapped in a ```json code fence are unwrapped before
detection / seeding.

Usage:
    python -m backend.eval.scripts.derive_minisset_expected_fields           # dry-run: print tiers + review queue
    python -m backend.eval.scripts.derive_minisset_expected_fields --write   # apply auto tiers + sentinel to the JSON
    python -m backend.eval.scripts.derive_minisset_expected_fields \
        --apply-review miniset-02=refuse miniset-04=answer ...               # record human-confirmed labels
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
MINISSET_PATH = REPO_ROOT / "backend/eval/datasets/_judge_minisset.json"

PENDING_SENTINEL = "PENDING AUDIT"
REFUSE_SUMMARY = "資料中確無此資訊，正確行為是如實說明來源內容沒有提到。"
ALLOWED_BEHAVIORS = ("answer", "refuse", "refusal_with_correction")

# Fixed refusal markers (covering 沒提到/未提及/無法回答/我不知道/找不到/沒有足夠資訊 類,
# incl. simplified-script variants the mini-set answers actually contain).
REFUSAL_PATTERN = re.compile(
    r"沒有?提到|没有?提到|沒有提及|未提及|未提到|無法回答|无法回答|我不知道|找不到"
    r"|沒有足夠資訊|沒有提供|没有提供|沒有關於|没有关于|無法得知|无法得知|無法確認|无法确认"
)

_JSON_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def unwrap_answer(answer: str) -> str:
    """Unwrap a ```json-fenced {"answer": ...} blob to its inner answer text."""
    m = _JSON_FENCE.match(answer.strip())
    if not m:
        return answer.strip()
    body = m.group(1)
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
            return parsed["answer"].strip()
    except json.JSONDecodeError:
        pass
    return body.strip()


def first_sentence(text: str) -> str:
    return text.split("。", 1)[0]


def is_refusal_shaped(answer: str) -> bool:
    return bool(REFUSAL_PATTERN.search(first_sentence(unwrap_answer(answer))))


def assign_tier(item: dict) -> str:
    """Tier from (refusal-shaped answer?, human_score). Returns auto_answer / auto_refuse / review."""
    if item["human_score"] <= 3:
        return "review"
    return "auto_refuse" if is_refusal_shaped(item["answer"]) else "auto_answer"


def derive(items: list[dict]) -> tuple[dict[str, str], list[str]]:
    """Return ({item_id: tier}, review_queue_ids) — deterministic over the same input."""
    tiers = {it["id"]: assign_tier(it) for it in items}
    review_queue = [it["id"] for it in items if tiers[it["id"]] == "review"]
    return tiers, review_queue


def apply_auto_fill(items: list[dict], tiers: dict[str, str]) -> None:
    """Fill auto tiers; review items get the sentinel and NO expected_behavior."""
    for it in items:
        tier = tiers[it["id"]]
        if tier == "auto_answer":
            it["expected_behavior"] = "answer"
            it["expected_answer_summary"] = unwrap_answer(it["answer"])
        elif tier == "auto_refuse":
            it["expected_behavior"] = "refuse"
            it["expected_answer_summary"] = REFUSE_SUMMARY
        else:  # review — sentinel only, label awaits human confirmation
            it["expected_answer_summary"] = PENDING_SENTINEL
            it.pop("expected_behavior", None)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive mini-set expected_* fields in tiers")
    parser.add_argument("--miniset", type=Path, default=MINISSET_PATH)
    parser.add_argument("--write", action="store_true",
                        help="Apply auto tiers + review sentinel to the mini-set JSON")
    parser.add_argument("--apply-review", nargs="+", metavar="ID=LABEL", default=None,
                        help="Record human-confirmed expected_behavior for review-queue items")
    args = parser.parse_args(argv)

    data = json.loads(args.miniset.read_text(encoding="utf-8"))
    items = data["items"]
    tiers, review_queue = derive(items)

    if args.apply_review:
        confirmed = 0
        for pair in args.apply_review:
            item_id, _, label = pair.partition("=")
            if label not in ALLOWED_BEHAVIORS:
                sys.exit(f"invalid label {label!r} for {item_id} (allowed: {ALLOWED_BEHAVIORS})")
            if tiers.get(item_id) != "review":
                sys.exit(f"{item_id} is not a review-queue item — refusing to overwrite an auto tier")
            item = next(it for it in items if it["id"] == item_id)
            item["expected_behavior"] = label
            confirmed += 1
        args.miniset.write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[apply-review] recorded {confirmed} human-confirmed label(s) → {args.miniset}")
        return 0

    print(f"{'id':<12} {'human':>5} {'refusal':>8} tier")
    print("-" * 44)
    for it in items:
        print(f"{it['id']:<12} {it['human_score']:>5} "
              f"{str(is_refusal_shaped(it['answer'])):>8} {tiers[it['id']]}")
    counts = {t: sum(1 for v in tiers.values() if v == t) for t in ("auto_answer", "auto_refuse", "review")}
    print(f"\ncounts: {counts}")
    print(f"review queue ({len(review_queue)}): {', '.join(review_queue)}")

    if args.write:
        apply_auto_fill(items, tiers)
        args.miniset.write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\n[write] auto tiers filled, review items sentinel'd → {args.miniset}")
    else:
        print("\n(dry-run — pass --write to apply auto tiers; review queue is never auto-filled)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
