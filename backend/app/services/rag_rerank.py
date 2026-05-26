"""LLM-driven rerank for the prefilter retrieval path.

Per change retrieval-cross-episode-chunk-recovery: after `retrieve_hybrid`
returns a top-N pool (N=50 for the prefilter path), call gemini-2.5-flash-lite
to reorder by question relevance and return the top-k.

Fail-open: any failure (timeout, non-2xx, malformed JSON, output references
unknown chunk_ids) falls back to the original RRF order's top-k. The caller
distinguishes success/failure via the returned `applied` boolean and SHOULD
log it on the agent envelope (envelope `rerank_applied` field) for RCA.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """\
You rerank Chinese-language podcast transcript chunks by how well each one answers the user's question.

You receive:
- A question (Chinese)
- A numbered list of chunks (each with a `chunk_id` and a short text excerpt)

Return ONLY a JSON object: {"ranked_chunk_ids": ["<chunk_id_1>", "<chunk_id_2>", ...]}
- Order chunks from MOST relevant to LEAST.
- Include every chunk_id you see, no duplicates, no extras.
- Output one JSON object, nothing else.

Relevance heuristics (apply in priority order):
1. Direct answer content (chunk explicitly says what the question asks).
2. Speaker/topic match — the chunk discusses the entities the question names.
3. Specific detail (chunks with concrete examples / quotes > chunks with abstract framing).
4. Avoid filler chunks (intro chatter, ad breaks, off-topic banter) — push these to the bottom.
"""

# Hard-code the rerank model. We reuse the `summary` step's base_url + api_key
# (Zeabur AI Hub) but lock the model so admin changes to summary don't
# silently change rerank behavior.
RERANK_MODEL = "gemini-2.5-flash-lite"
_DEFAULT_EXCERPT_CHARS = 200


def _build_user_content(question: str, chunks: list[dict]) -> str:
    parts = [f"question: {question.strip()}", "", "chunks:"]
    for i, c in enumerate(chunks, start=1):
        cid = c.get("chunk_id", "")
        text = (c.get("text") or "").strip().replace("\n", " ")
        if len(text) > _DEFAULT_EXCERPT_CHARS:
            text = text[:_DEFAULT_EXCERPT_CHARS] + "…"
        parts.append(f"{i}. chunk_id={cid} | {text}")
    return "\n".join(parts)


async def llm_rerank(
    question: str,
    chunks: list[dict],
    k: int,
    *,
    client: AsyncOpenAI,
    model: str = RERANK_MODEL,
    timeout_s: float = 3.0,
) -> tuple[list[dict], bool]:
    """Rerank chunks by LLM and return top-k.

    Returns:
        (chunks_top_k, applied) — `applied=True` when rerank produced a usable
        ordering, `False` when the original RRF order was used as fallback.

    Failure modes that all fall back (applied=False):
        - asyncio.TimeoutError or any LLM-side exception
        - LLM returns empty / malformed JSON
        - LLM output's `ranked_chunk_ids` is missing or not a list
        - All returned chunk_ids are unknown (none match input)

    Partial-unknown handling: unknown chunk_ids are discarded; if fewer than k
    valid chunks remain after dedup, the gap is back-filled from the original
    chunks in their input order. `applied=True` in this partial case — the
    LLM's signal is still informative.
    """
    if not chunks:
        return [], False
    if len(chunks) <= k:
        # Nothing to rerank — trivial top-k.
        return chunks[:k], False

    chunks_by_id: dict[str, dict] = {}
    for c in chunks:
        cid = c.get("chunk_id")
        if cid is not None:
            chunks_by_id[str(cid)] = c

    user_content = _build_user_content(question, chunks)
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            ),
            timeout=timeout_s,
        )
    except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001 — fail-open
        logger.warning("rerank fallback (api error): %s", exc.__class__.__name__)
        return chunks[:k], False

    content = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not content:
        logger.warning("rerank fallback: empty response")
        return chunks[:k], False

    # AI Hub gpt-4o-style wrap with ```json fences; strip defensively.
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("rerank fallback (invalid json): %s; content=%r", exc, content[:200])
        return chunks[:k], False

    if not isinstance(parsed, dict):
        logger.warning("rerank fallback: response not an object")
        return chunks[:k], False

    ranked_ids = parsed.get("ranked_chunk_ids")
    if not isinstance(ranked_ids, list):
        logger.warning("rerank fallback: ranked_chunk_ids missing or not a list")
        return chunks[:k], False

    seen: set[str] = set()
    reordered: list[dict] = []
    for cid in ranked_ids:
        cid_str = str(cid)
        if cid_str in seen:
            continue
        c = chunks_by_id.get(cid_str)
        if c is None:
            # Unknown chunk_id — silently drop.
            continue
        seen.add(cid_str)
        reordered.append(c)

    if not reordered:
        logger.warning("rerank fallback: no known chunk_ids in response")
        return chunks[:k], False

    # Back-fill any shortfall from the original input order.
    if len(reordered) < k:
        for c in chunks:
            cid_str = str(c.get("chunk_id", ""))
            if cid_str in seen or cid_str == "":
                continue
            seen.add(cid_str)
            reordered.append(c)
            if len(reordered) >= k:
                break

    return reordered[:k], True
