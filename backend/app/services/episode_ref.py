"""Episode-reference extraction for the public search endpoint.

`/shows/{id}/search` queries that mention `EP<N>` (e.g. "迪拉胖在 EP134 為什麼
不挑振奮的開工歌") used to score Recall@5 = 0 because retrieval embedding /
BM25 cannot match the literal token `EP134` to transcript chunks that simply
talk about "馬力全開" / "安身之處". This helper resolves the EP-reference
upfront so the endpoint can pass `episode_id_filter` to `retrieve_hybrid`.

Spec: chat-agentic-routing → no change (agent already has find_episode_by_ref
+ search_within_episode tools). Only the public /search endpoint needed this
plumbing.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Case-insensitive: matches "EP134", "ep 134", "Ep143". The optional whitespace
# tolerates user typos. We deliberately do NOT match Chinese "第N集" here —
# that case has multi-turn carry semantics handled inside the chat agent
# (ordinal tool), not by chunk-level filtering at the search endpoint.
_EP_REF_RE = re.compile(r"EP\s*(\d+)", re.IGNORECASE)

# Anchored regex on the Postgres side: episode title must start with `EP<N>`
# followed by either a non-digit (e.g. `｜`, ` `, `:`) or end-of-string. Without
# the boundary, `EP1` would also match `EP10`, `EP14`, `EP143`.
_EPISODE_LOOKUP_SQL = """
SELECT id
FROM episodes
WHERE show_id = :show_id
  AND title ~ ('^EP' || :n || '(\\D|$)')
LIMIT 1
"""


async def extract_episode_ids_from_query(
    db: AsyncSession, show_id: uuid.UUID, query: str
) -> list[uuid.UUID]:
    """Return episode UUIDs for every `EP<N>` reference in `query`.

    Order of returned UUIDs matches the order of first appearance in the
    query, deduplicated. Numbers without a matching episode on the given
    `show_id` are skipped with a `logger.warning` (so operators can spot
    user typos like `EP999`); the caller treats an empty list as "no
    episode filter, run unfiltered search".
    """
    if not query:
        return []
    numbers: list[str] = []
    seen: set[str] = set()
    for m in _EP_REF_RE.finditer(query):
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            numbers.append(n)
    if not numbers:
        return []

    ids: list[uuid.UUID] = []
    for n in numbers:
        result = await db.execute(
            text(_EPISODE_LOOKUP_SQL), {"show_id": show_id, "n": n}
        )
        row = result.mappings().first()
        if row is None:
            logger.warning(
                "episode_ref: number EP%s not found in show %s", n, show_id
            )
            continue
        ids.append(row["id"])
    return ids
