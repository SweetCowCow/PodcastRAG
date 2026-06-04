"""Backend service layer for the lexical-mismatch query-rewrite bake-off.

change: lexical-mismatch-query-rewrite-bakeoff (EQ3b family).

Each arm rewrites/augments a query *before* it enters the shared downstream
`rag.retrieve_hybrid`. An arm returns one or more `RetrievePlan`s — each plan is
a `(lexical_question, embedding)` pair the endpoint feeds into retrieve_hybrid.
The endpoint merges plans by taking each chunk's best (min) rank across plans,
so `multi-vector` (N plans) needs no change to the online retrieve path.

This runs server-side (admin diagnose endpoint) because `embed_texts` needs the
DB step config and `retrieve_hybrid` needs a DB session reaching prod's pgvector
— a local HTTP script cannot. Arms hold no opinion on landing; they only measure
(see design.md stop-the-line decision).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from openai import OpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_step_resolver import StepConfig, get_step_config
from app.services.embedding import embed_texts

ARMS: tuple[str, ...] = ("control", "query-expansion", "hyde", "multi-vector")

# Fixed prompts (temperature=0) so HyDE / expansion output is reproducible per
# design Risks/Trade-offs. Tuned for Mandarin podcast transcripts.
_EXPANSION_SYSTEM = (
    "你是中文檢索查詢擴充器。針對使用者的問題，列出 5-8 個答案內容裡可能出現的"
    "同義詞、近義詞、口語說法與相關概念詞（書面與口語都要）。"
    "只輸出這些詞語、以空格分隔，不要編號、不要解釋、不要重複原問題整句。"
)
_HYDE_SYSTEM = (
    "你是 podcast 逐字稿模擬器。針對使用者的問題，用講者口吻寫一段 2-3 句、"
    "像逐字稿口語的假設性回答內容，盡量包含答案可能出現的具體說法與詞彙。"
    "只輸出這段內容，不要前後綴、不要解釋。"
)
_MULTIVEC_SYSTEM = (
    "把使用者的問題拆成 2-3 個語意面向的子查詢，每個子查詢聚焦問題的一個面向"
    "（例如人物、事件、時間、因果）。每行輸出一個子查詢，不要編號、不要解釋。"
)


@dataclass
class RetrievePlan:
    """One retrieve invocation: a lexical question + a query embedding."""

    lexical_question: str
    embedding: list[float]


@dataclass
class ArmResult:
    plans: list[RetrievePlan]
    extra_llm_calls: int
    llm_ms: float
    rewrite_debug: dict = field(default_factory=dict)


def _chat(client: OpenAI, model: str | None, system: str, user: str) -> tuple[str, float]:
    """One temperature=0 chat call. Returns (content, elapsed_ms)."""
    start_ns = time.monotonic_ns()
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
    return (resp.choices[0].message.content or "").strip(), elapsed_ms


async def apply_arm(
    arm: str,
    question: str,
    db: AsyncSession,
    embed_step: StepConfig,
) -> ArmResult:
    """Apply one bake-off arm to a question, returning retrieve plans + cost.

    `control` is the baseline: original question, single embedding, 0 LLM calls
    (behaviourally equivalent to the existing prefilter-rank endpoint).
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm!r}; expected one of {ARMS}")

    base_vec = embed_texts([question], embed_step)[0]

    if arm == "control":
        return ArmResult(
            plans=[RetrievePlan(question, base_vec)],
            extra_llm_calls=0,
            llm_ms=0.0,
            rewrite_debug={"arm": "control"},
        )

    chat_step = await get_step_config(db, "answer")
    client = OpenAI(base_url=chat_step.base_url, api_key=chat_step.api_key)
    model = chat_step.model

    if arm == "query-expansion":
        terms, ms = _chat(client, model, _EXPANSION_SYSTEM, question)
        lexical = f"{question} {terms}".strip()
        return ArmResult(
            plans=[RetrievePlan(lexical, base_vec)],
            extra_llm_calls=1,
            llm_ms=ms,
            rewrite_debug={"arm": arm, "model": model, "expansion_terms": terms,
                           "lexical_question": lexical},
        )

    if arm == "hyde":
        hyde_text, ms = _chat(client, model, _HYDE_SYSTEM, question)
        hyde_text = hyde_text or question
        hyde_vec = embed_texts([hyde_text], embed_step)[0]
        return ArmResult(
            plans=[RetrievePlan(question, hyde_vec)],
            extra_llm_calls=1,
            llm_ms=ms,
            rewrite_debug={"arm": arm, "model": model, "hyde_text": hyde_text},
        )

    # multi-vector
    raw, ms = _chat(client, model, _MULTIVEC_SYSTEM, question)
    subqueries = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not subqueries:
        subqueries = [question]
    sub_vecs = embed_texts(subqueries, embed_step)
    plans = [RetrievePlan(question, v) for v in sub_vecs]
    return ArmResult(
        plans=plans,
        extra_llm_calls=1,
        llm_ms=ms,
        rewrite_debug={"arm": arm, "model": model, "subqueries": subqueries,
                       "aggregation": "min-rank-across-plans"},
    )
