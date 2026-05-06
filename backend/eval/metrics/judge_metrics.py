"""LLM-judge metric for production eval — wraps DeepEval GEval.

The judge model is locked in `backend/eval/judge_config.py:PRODUCTION_JUDGE_MODEL`.
Bake-off rationale and Spearman calibration debt: see the docstring there.
"""
from __future__ import annotations

import os

from backend.eval.judge_config import JUDGE_PROVIDER_BASE_URL, PRODUCTION_JUDGE_MODEL

GEVAL_CRITERIA = """評估這個答案在給定 retrieval context 下的整體可信度與相關性，給 1-5 分。

- 5 分：答案完全基於 context，正確、完整、措辭得體；若 context 無相關資訊，答案應誠實承認
- 4 分：答案大致基於 context，正確但可能有小遺漏或措辭可改善
- 3 分：答案部分基於 context，遺漏明顯資訊、或回答只有一半正確
- 2 分：答案與 context 關聯薄弱，或包含 context 未支持的資訊（部分捏造）
- 1 分：答案與 context 不符、明顯捏造、誤導性、或答非所問

特別注意：
- 「context 沒提到」這種誠實回答，若 context 確實沒提到 → 5 分
- 若 context 其實有提到、但答案說「沒提到」→ 1-2 分
- 中英夾雜、口語化都不扣分，只看 grounding 與相關性
"""


def judge_score(
    question: str,
    answer: str,
    context: list[str],
    model: str | None = None,
) -> float:
    """GEval score in [0, 1] (DeepEval normalises the 1-5 rubric).

    Caller provides retrieval context (segment texts). Caller is responsible for
    setting OPENAI_API_KEY env (used as the hub bearer token).
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    os.environ.setdefault("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    os.environ["OPENAI_BASE_URL"] = JUDGE_PROVIDER_BASE_URL

    metric = GEval(
        name="TrustGroundedness",
        criteria=GEVAL_CRITERIA,
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.RETRIEVAL_CONTEXT,
        ],
        model=model or PRODUCTION_JUDGE_MODEL,
        async_mode=False,
        threshold=0.0,
    )
    case = LLMTestCase(
        input=question,
        actual_output=answer,
        retrieval_context=context,
    )
    metric.measure(case)
    return float(metric.score)
