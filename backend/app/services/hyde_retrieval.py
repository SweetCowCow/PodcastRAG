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
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from openai import OpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import tokenizer
from app.services.ai_step_resolver import (
    AiStepNotConfiguredError,
    StepConfig,
    get_step_config,
)
from app.services.embedding import embed_texts
# Source of truth for the HyDE prompt + single temperature=0 chat call: the
# archived lexical-mismatch-query-rewrite-bakeoff hyde arm (quantitative winner).
from app.services.lexical_bakeoff_arms import _HYDE_SYSTEM, _chat

if TYPE_CHECKING:  # avoid runtime import cycle; we only read `.text`
    from app.services.rag import ChunkHit

logger = logging.getLogger(__name__)

# CJK range — single-char latin tokens are dropped, single-char CJK kept,
# mirroring rag._build_ts_query's token cleaning so the overlap signal aligns
# with what the lexical (BM25) side actually keys on.
_CJK_RE = re.compile(r"[一-鿿]")


def _meaningful_query_tokens(question: str) -> list[str]:
    """Jieba-tokenise `question` and keep the discriminating tokens.

    Mirrors `rag._build_ts_query`: drop pure-punctuation tokens, single-char
    non-CJK tokens, and show-name terms (too generic — they appear across every
    episode and would inflate overlap). Returns the cleaned token list.
    """
    show_name_terms = tokenizer.get_show_name_terms()
    cleaned: list[str] = []
    for tok in tokenizer.tokenize(question):
        tok = tok.strip()
        if not tok or re.fullmatch(r"\W+", tok):
            continue
        if len(tok) < 2 and not _CJK_RE.search(tok):
            continue
        if tok in show_name_terms:
            continue
        cleaned.append(tok)
    return cleaned


def lexical_overlap_ratio(question: str, hits: list["ChunkHit"]) -> float:
    """Fraction of the question's distinct meaningful tokens that appear in the
    text of `hits`.

    Returns a value in [0, 1]: ~1.0 when every query token is present in the
    recalled chunk text (lexical hit — answer phrased like the question), ~0.0
    when none are (lexical mismatch — answer phrased differently). Returns 0.0
    when the question has no meaningful tokens or `hits` is empty, so the caller
    treats "no lexical signal" as mismatch and lets HyDE try.
    """
    tokens = set(_meaningful_query_tokens(question))
    if not tokens:
        return 0.0
    corpus = " ".join((h.text or "") for h in hits)
    if not corpus:
        return 0.0
    present = sum(1 for tok in tokens if tok in corpus)
    return present / len(tokens)


@dataclass
class HydeResult:
    """Resolved chunk-recall semantic vector + observability fields."""

    semantic_vec: list[float]
    used_hyde: bool
    hyde_text: str | None
    extra_llm_calls: int
    # hyde-conditional-activation observability. Defaults keep every existing
    # `resolve_semantic_embedding` construction site valid: the unconditional
    # path never runs two-stage, so conditional_mode=False / overlap_ratio=None.
    conditional_mode: bool = False
    overlap_ratio: float | None = None
    triggered_by_mismatch: bool = False


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


async def resolve_chunk_hits_conditional(
    db: AsyncSession,
    question: str,
    base_vec: list[float],
    embedding_cfg: StepConfig,
    *,
    retrieve: Callable[[list[float]], Awaitable[list["ChunkHit"]]],
) -> tuple[list["ChunkHit"], HydeResult]:
    """Two-stage conditional HyDE: recall once, then HyDE only on mismatch.

    Callers pass a `retrieve` closure that runs `rag.retrieve_hybrid` with the
    show_id / k / episode filter already bound, taking only the chunk-recall
    semantic vector. The orchestrator:

      1. runs a base recall with `base_vec`,
      2. measures `lexical_overlap_ratio(question, base_hits[:hyde_mismatch_topn])`,
      3. if overlap >= `hyde_mismatch_overlap_threshold` → returns the base hits
         (no HyDE call, no second recall),
      4. else generates HyDE (reusing `resolve_semantic_embedding`, which runs
         because both flags are on) and re-retrieves with the HyDE vector.

    Fail-open: a failure in overlap computation, HyDE generation, or the second
    recall returns the base hits with `triggered_by_mismatch=False`; it never
    raises. The stage-1 base recall is awaited directly — a failure there
    surfaces exactly as in the non-conditional path (no new swallowing).
    """
    base_hits = await retrieve(base_vec)

    try:
        overlap = lexical_overlap_ratio(
            question, base_hits[: settings.hyde_mismatch_topn]
        )
    except Exception as exc:  # noqa: BLE001 — fail-open to base hits
        logger.warning(
            "hyde-conditional: overlap computation failed; fail-open base: %s", exc
        )
        return base_hits, HydeResult(
            base_vec, used_hyde=False, hyde_text=None, extra_llm_calls=0,
            conditional_mode=True, overlap_ratio=None, triggered_by_mismatch=False,
        )

    if overlap >= settings.hyde_mismatch_overlap_threshold:
        # Lexical aligns — answer phrased like the question. Skip HyDE entirely.
        return base_hits, HydeResult(
            base_vec, used_hyde=False, hyde_text=None, extra_llm_calls=0,
            conditional_mode=True, overlap_ratio=overlap, triggered_by_mismatch=False,
        )

    # Mismatch detected — generate HyDE. resolve_semantic_embedding runs because
    # both flags are on (master gate True); it is itself fully fail-open.
    gen = await resolve_semantic_embedding(db, question, base_vec, embedding_cfg)
    if not gen.used_hyde:
        # Generation/embedding failed-open inside the helper → keep base hits.
        return base_hits, HydeResult(
            base_vec, used_hyde=False, hyde_text=gen.hyde_text,
            extra_llm_calls=gen.extra_llm_calls,
            conditional_mode=True, overlap_ratio=overlap, triggered_by_mismatch=False,
        )

    try:
        hyde_hits = await retrieve(gen.semantic_vec)
    except Exception as exc:  # noqa: BLE001 — fail-open to base hits
        logger.warning(
            "hyde-conditional: second retrieve failed; fail-open base: %s", exc
        )
        return base_hits, HydeResult(
            base_vec, used_hyde=False, hyde_text=gen.hyde_text,
            extra_llm_calls=gen.extra_llm_calls,
            conditional_mode=True, overlap_ratio=overlap, triggered_by_mismatch=False,
        )

    return hyde_hits, HydeResult(
        gen.semantic_vec, used_hyde=True, hyde_text=gen.hyde_text,
        extra_llm_calls=gen.extra_llm_calls,
        conditional_mode=True, overlap_ratio=overlap, triggered_by_mismatch=True,
    )
