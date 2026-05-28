"""Per-show IDF cache for transcript lexical retrieval weighting.

Backs `Decision A1` / `A2` of change `retrieve-quality-step1-idf-and-prefilter`:
- `refresh_freq_table(db, show_id)` scans `transcript_chunks.text_tsvector`
  via PG `ts_stat` and upserts (token, df, idf) into `transcript_token_freq`.
- `get_idf_buckets(db, show_id, tokens)` looks up IDF per token and maps to
  one of four bucket labels (A/B/C/D) used by the bucketed `ts_rank` sum
  in `_TRANSCRIPT_RRF_SQL`.
- `build_bucketed_ts_queries(ts_query, buckets)` splits the OR-joined ts_query
  string into 4 sub-queries (per bucket) for the SQL CASE WHEN sum.
"""
from __future__ import annotations

import logging
import time
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# IDF thresholds → bucket label (A=rarest, D=most common).
# See design.md Decision A2 (revised).
_IDF_THRESHOLDS: list[tuple[float, str]] = [
    (8.0, "A"),
    (5.0, "B"),
    (2.0, "C"),
]
_DEFAULT_BUCKET = "D"
_MISSING_BUCKET = "C"  # neutral fallback per spec scenario


def _bucket_for_idf(idf: float) -> str:
    for threshold, label in _IDF_THRESHOLDS:
        if idf > threshold:
            return label
    return _DEFAULT_BUCKET


async def refresh_freq_table(db: AsyncSession, show_id: uuid.UUID) -> dict:
    """Recompute token document-frequency for one show and upsert into
    `transcript_token_freq`.

    Uses PG `ts_stat` over the existing `text_tsvector` so the lexicon
    matches retrieval-side `to_tsquery('simple', ...)` tokens exactly.

    Returns `{tokens_written, total_docs, elapsed_ms}`.
    """
    started = time.perf_counter()
    show_id_str = str(show_id)
    # UUID type-checked above; safe to inline in the inner SQL literal that
    # `ts_stat` requires (it takes a SQL string, not a bound param).

    total_docs_row = await db.execute(
        text(
            "SELECT COUNT(*) AS n FROM transcript_chunks c "
            "JOIN transcripts t ON t.id = c.transcript_id "
            "JOIN episodes e ON e.id = t.episode_id "
            "WHERE e.show_id = :show_id AND t.status = 'completed' "
            "AND c.text_tsvector IS NOT NULL"
        ),
        {"show_id": show_id},
    )
    total_docs = int(total_docs_row.scalar() or 0)
    if total_docs == 0:
        logger.warning("refresh_freq_table: no completed transcript chunks for show %s", show_id)
        return {"tokens_written": 0, "total_docs": 0, "elapsed_ms": 0}

    inner_sql = (
        "SELECT c.text_tsvector FROM transcript_chunks c "
        "JOIN transcripts t ON t.id = c.transcript_id "
        "JOIN episodes e ON e.id = t.episode_id "
        f"WHERE e.show_id = '{show_id_str}'::uuid "
        "AND t.status = 'completed' AND c.text_tsvector IS NOT NULL"
    )
    stat_rows = await db.execute(
        text("SELECT word, ndoc FROM ts_stat(:inner)"),
        {"inner": inner_sql},
    )
    stats = [(r["word"], int(r["ndoc"])) for r in stat_rows.mappings()]
    if not stats:
        return {"tokens_written": 0, "total_docs": total_docs, "elapsed_ms": 0}

    # Delete existing rows for this show, then bulk insert. Simpler than
    # row-level upsert and idempotent per spec scenario.
    await db.execute(
        text("DELETE FROM transcript_token_freq WHERE show_id = :show_id"),
        {"show_id": show_id},
    )

    insert_sql = text(
        "INSERT INTO transcript_token_freq (show_id, token, df, total_docs, idf, updated_at) "
        "VALUES (:show_id, :token, :df, :total_docs, :idf, NOW())"
    )
    import math
    payload = [
        {
            "show_id": show_id,
            "token": word,
            "df": df,
            "total_docs": total_docs,
            "idf": math.log((total_docs + 1) / (df + 1)),
        }
        for word, df in stats
    ]
    # Batch inserts in chunks to avoid huge single statements
    BATCH = 1000
    for i in range(0, len(payload), BATCH):
        await db.execute(insert_sql, payload[i : i + BATCH])
    await db.commit()

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "refresh_freq_table show=%s tokens=%d total_docs=%d elapsed_ms=%d",
        show_id, len(stats), total_docs, elapsed_ms,
    )
    return {"tokens_written": len(stats), "total_docs": total_docs, "elapsed_ms": elapsed_ms}


async def get_idf_buckets(
    db: AsyncSession, show_id: uuid.UUID, tokens: list[str]
) -> dict[str, str]:
    """Look up IDF for each token in `tokens` and return token → bucket label.

    Missing tokens fall back to the neutral bucket `C` and emit a warning log.
    Raises only on infrastructure errors (e.g. DB connection); caller is
    expected to catch and fall back to the legacy unweighted SQL path.
    """
    if not tokens:
        return {}
    unique = list(set(tokens))
    rows = await db.execute(
        text(
            "SELECT token, idf FROM transcript_token_freq "
            "WHERE show_id = :show_id AND token = ANY(:tokens)"
        ),
        {"show_id": show_id, "tokens": unique},
    )
    idf_map = {r["token"]: float(r["idf"]) for r in rows.mappings()}
    result: dict[str, str] = {}
    missing: list[str] = []
    for tok in unique:
        if tok in idf_map:
            result[tok] = _bucket_for_idf(idf_map[tok])
        else:
            result[tok] = _MISSING_BUCKET
            missing.append(tok)
    if missing:
        logger.warning(
            "get_idf_buckets show=%s missing %d/%d tokens (fallback to %s): %s",
            show_id, len(missing), len(unique), _MISSING_BUCKET, missing[:5],
        )
    return result


def build_bucketed_ts_queries(
    ts_query: str, buckets: dict[str, str]
) -> dict[str, str | None]:
    """Split an OR-joined ts_query string into 4 per-bucket sub-queries.

    Input `ts_query` looks like `"迪拉胖 | 的 | 振奮"` (from `_build_ts_query`).
    `buckets` maps each token to one of 'A'/'B'/'C'/'D'.
    Returns `{"a": "迪拉胖 | 振奮", "b": None, "c": "的", "d": None}`
    (lowercase keys, empty buckets → None for SQL CASE WHEN).
    """
    tokens = [t.strip() for t in ts_query.split("|") if t.strip()]
    grouped: dict[str, list[str]] = {"A": [], "B": [], "C": [], "D": []}
    for tok in tokens:
        label = buckets.get(tok, _MISSING_BUCKET)
        grouped[label].append(tok)
    return {
        "a": " | ".join(grouped["A"]) if grouped["A"] else None,
        "b": " | ".join(grouped["B"]) if grouped["B"] else None,
        "c": " | ".join(grouped["C"]) if grouped["C"] else None,
        "d": " | ".join(grouped["D"]) if grouped["D"] else None,
    }
