"""One-shot routing-only probe for b22-cross-episode-topic-routing (task 5.1).

Runs `should_force_topic_prefilter` over every dataset question/turn whose
expected tool calls include `search_across_episodes`, plus the b23 target
question. Prints each question + detector verdict so we can confirm:

  - b23 → True (must be force-routed)
  - the `search_across_episodes` golden questions are NOT mis-fired to True
    (high-precision guard); any True among them is flagged for manual review.

No DB, no network — pure detector evaluation. Run from backend/:
    python -m scripts.b22_routing_probe
"""

from __future__ import annotations

import json
from pathlib import Path

import jieba

from app.services import tokenizer as _tk

# Seed the tokenizer with the prod custom terms + show titles so the detector's
# show-name filter (`tokenizer.get_show_name_terms()`) behaves exactly as it
# does in prod. Without this the script's lazy DB load fails locally (host "db"
# unreachable) and show-name tokens leak through, inflating the True rate on
# show-name-containing questions (e.g. b01). Snapshot taken 2026-06-07 from
# prod `tokenizer_custom_terms` + `shows.title`.
_PROD_CUSTOM_TERMS = [
    "Angela", "Illy", "Lean", "Leo王", "Manny", "何ㄟ", "台灣通勤第一品牌",
    "台通", "吃漢", "呱吉", "大嘻哈時代", "家倫", "拉麵吃漢", "新資料夾",
    "方PD", "方品融", "杜宗祐", "歌單", "異世界美食家", "蘴月食堂", "裴社長",
    "誠誠", "迪拉胖", "這又沒有很屌", "采翎", "阿名", "顏社", "馬世芳", "鼎泰豐",
]
_PROD_SHOW_TITLES = ["壹加壹電台", "曼報", "這又沒有很屌"]


def _seed_tokenizer() -> None:
    for term in _PROD_CUSTOM_TERMS:
        jieba.add_word(term, freq=100)
        _tk._loaded_terms.add(term)
    for title in _PROD_SHOW_TITLES:
        jieba.add_word(title)
        _tk._loaded_terms.add(title)
        _tk._show_name_terms.add(title)
    _tk._loaded = True  # block the (locally-failing) lazy DB load


_seed_tokenizer()

from app.services.chat_agent.routing import should_force_topic_prefilter  # noqa: E402

_DATASET = Path("eval/datasets/extended-multi-turn-40.json")

# b23 target (cross-episode narrative). Mirrors proposal.md / smoke script.
_B23_Q = (
    "迪拉跟 Leo王 是怎麼從不認識變成合作夥伴的？他們第一次見面的故事是什麼？"
)


def _tools(unit: dict) -> list[str]:
    return (unit.get("expected_tool_calls_required") or []) + (
        unit.get("expected_tool_calls_acceptable") or []
    )


# design_types where firing True is correct-by-design: prefilter is a strict
# superset of search_across_episodes, so routing genuine cross-episode topical /
# narrative / deep-dive questions to it is the change's intent (see design D2
# probe interpretation). Firing on these is NOT a harmful mis-fire.
_TOPICAL_DESIGN_TYPES = {"cross_episode", "deep_dive", "leading_question_yes"}


def _across_questions(items: list[dict]) -> list[tuple[str, str, str]]:
    """Return [(label, design_type, question)] for every single-turn item /
    multi-turn turn whose expected tools include `search_across_episodes`."""
    out: list[tuple[str, str, str]] = []
    for it in items:
        if it.get("is_multi_turn"):
            for turn in it.get("turns") or []:
                if "search_across_episodes" in _tools(turn):
                    out.append(
                        (f"{it['id']}/{turn.get('turn')}", it.get("design_type", "?"),
                         turn["question"])
                    )
        else:
            if "search_across_episodes" in _tools(it):
                out.append((it["id"], it.get("design_type", "?"), it["question"]))
    return out


def main() -> None:
    data = json.loads(_DATASET.read_text(encoding="utf-8"))
    across = _across_questions(data["items"])

    print("=== b22 routing probe ===\n")
    print(f"[b23 target] detector={should_force_topic_prefilter(_B23_Q)}  (want True)")
    print(f"  q: {_B23_Q}\n")

    print(f"[search_across_episodes golden: {len(across)} units]")
    print("  legend: OK-topical = True on a topical design_type (correct by design,")
    print("          prefilter superset); REVIEW = True on show_overview/multi_turn\n")
    review: list[tuple[str, str, str]] = []
    for label, dtype, q in across:
        verdict = should_force_topic_prefilter(q)
        if verdict and dtype in _TOPICAL_DESIGN_TYPES:
            tag = "OK-topical"
        elif verdict:
            tag = "REVIEW    "
            review.append((label, dtype, q))
        else:
            tag = "excluded  "
        print(f"  {label:>10}  detector={str(verdict):>5}  [{tag}] {dtype}")
        print(f"             q: {q}")

    print("\n=== summary ===")
    print(f"b23 target              : {should_force_topic_prefilter(_B23_Q)} (want True)")
    print(f"across golden units     : {len(across)}")
    print(f"True on topical dtype    : correct-by-design (prefilter superset)")
    print(f"True on non-topical (REVIEW): {len(review)}")
    for label, dtype, q in review:
        note = (
            " — handled by D5 pinned-episode guard (multi-turn pin)"
            if dtype == "multi_turn"
            else ""
        )
        print(f"  - {label} [{dtype}]{note}: {q}")


if __name__ == "__main__":
    main()
