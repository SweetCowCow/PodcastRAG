"""Flag-gated HyDE (Hypothetical Document Embeddings) for chunk retrieval.

change: hyde-retrieval-landing.

The online semantic-retrieve entry points feed one `query_embedding` to BOTH
`route_episodes` (episode selection) and `rag.retrieve_hybrid` (chunk recall).
This helper resolves *only* the chunk-recall semantic vector:

  - `enable_hyde_retrieval=False` (default): returns `base_vec` unchanged — the
    embedding of the original (or history-rewritten) question, 0 extra LLM calls,
    no HyDE code path entered. Bit-equivalent to the pre-change behaviour.
  - `enable_hyde_retrieval=True`: generates a short hypothetical-answer text
    (temperature=0, fixed prompt) and returns its embedding instead. Callers
    keep `base_vec` for `route_episodes` and keep the original question for the
    BM25 lexical side — only the chunk-recall semantic vector changes.

HyDE generation is best-effort: any failure (step not configured, client ctor,
LLM error, empty response) fails open to `base_vec` with a logged warning and
never raises — the retrieve path MUST NOT 5xx because HyDE failed (mirrors
`_extract_entities_fail_open`). The HyDE system prompt and control-equivalent
logic are reused from the archived bake-off (`lexical_bakeoff_arms._HYDE_SYSTEM`),
which is the quantitative winner this change lands.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from openai import OpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.ai_step_resolver import (
    AiStepNotConfiguredError,
    StepConfig,
    get_step_config,
)
from app.services.embedding import embed_texts
# Source of truth for the HyDE prompt + single temperature=0 chat call: the
# archived lexical-mismatch-query-rewrite-bakeoff hyde arm (quantitative winner).
from app.services.lexical_bakeoff_arms import _HYDE_SYSTEM, _chat

logger = logging.getLogger(__name__)


@dataclass
class HydeResult:
    """Resolved chunk-recall semantic vector + observability fields."""

    semantic_vec: list[float]
    used_hyde: bool
    hyde_text: str | None
    extra_llm_calls: int


async def resolve_semantic_embedding(
    db: AsyncSession,
    question: str,
    base_vec: list[float],
    embedding_cfg: StepConfig,
) -> HydeResult:
    """Resolve the semantic vector for `rag.retrieve_hybrid`'s chunk recall.

    `base_vec` is the caller's already-computed embedding of `question` (the
    original or history-rewritten question), which `route_episodes` also uses.

    Flag off → returns `base_vec` (used_hyde=False, extra_llm_calls=0). Flag on
    → generates a HyDE text from `question` and returns its embedding; any
    failure falls open to `base_vec` (used_hyde=False) without raising.
    """
    if not settings.enable_hyde_retrieval:
        return HydeResult(
            semantic_vec=base_vec,
            used_hyde=False,
            hyde_text=None,
            extra_llm_calls=0,
        )

    # --- flag on: generate hypothetical answer text, embed it (fail-open) ---
    try:
        chat_cfg = await get_step_config(db, "answer")
    except AiStepNotConfiguredError as exc:
        logger.warning("hyde: answer step not configured; fail-open: %s", exc)
        return HydeResult(base_vec, used_hyde=False, hyde_text=None, extra_llm_calls=0)

    try:
        client = OpenAI(base_url=chat_cfg.base_url, api_key=chat_cfg.api_key)
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("hyde: OpenAI ctor failed; fail-open: %s", exc)
        return HydeResult(base_vec, used_hyde=False, hyde_text=None, extra_llm_calls=0)

    try:
        hyde_text, _ms = await asyncio.to_thread(
            _chat, client, chat_cfg.model, _HYDE_SYSTEM, question
        )
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("hyde: generation LLM call failed; fail-open: %s", exc)
        return HydeResult(base_vec, used_hyde=False, hyde_text=None, extra_llm_calls=1)

    if not hyde_text:
        logger.warning("hyde: empty generation; fail-open to base_vec")
        return HydeResult(base_vec, used_hyde=False, hyde_text=None, extra_llm_calls=1)

    try:
        hyde_vec = (await asyncio.to_thread(embed_texts, [hyde_text], embedding_cfg))[0]
    except Exception as exc:  # noqa: BLE001 — fail-open
        logger.warning("hyde: embedding HyDE text failed; fail-open: %s", exc)
        return HydeResult(base_vec, used_hyde=False, hyde_text=hyde_text, extra_llm_calls=1)

    return HydeResult(
        semantic_vec=hyde_vec,
        used_hyde=True,
        hyde_text=hyde_text,
        extra_llm_calls=1,
    )
