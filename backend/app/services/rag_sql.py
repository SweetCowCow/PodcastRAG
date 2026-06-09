"""RAG SQL building blocks.

Lexical/vector query construction + the hybrid retrieval SQL templates. Depends
on ``rag_config`` (embedding-column flags, read at call time so reload tests
see fresh values) and ``rag_types`` (MetadataFilters). The biggest piece here,
``_build_ts_query``, is the future BM25 target (EQ3c).
"""
from __future__ import annotations

import json as _stdlib_json
import re
import uuid

from app.services import rag_config, tokenizer
from app.services.rag_types import MetadataFilters

__all__ = [
    "_vector_literal",
    "_build_ts_query",
    "_validate_query_dim",
    "_episode_filter_clause",
    "_metadata_filter_clause",
    "_TRANSCRIPT_RRF_SQL",
    "_TRANSCRIPT_SEMANTIC_ONLY_SQL",
    "_DESC_RRF_SQL",
    "_DESC_SEMANTIC_ONLY_SQL",
    "_TITLE_LEXICAL_SQL",
    "_ROUTE_EPISODES_SQL",
]


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _validate_query_dim(query_embedding: list[float]) -> None:
    """Hard error when caller hands us an embedding whose dim doesn't match
    the column we're about to read. Catches the spec scenario "dim mismatch
    is a hard error" — happens when ai_steps points at a model whose native
    dim != expected for the active column.

    Reads the expected dim from ``rag_config`` at call time so unit tests that
    reload ``rag_config`` (to flip RAG_USE_EMBEDDING_V2) see the fresh value.
    """
    if not query_embedding:
        return
    if len(query_embedding) != rag_config._EXPECTED_QUERY_DIM:
        raise RuntimeError(
            f"rag: query embedding dim {len(query_embedding)} does not match "
            f"expected dim {rag_config._EXPECTED_QUERY_DIM} for the active "
            f"embedding column "
            f"(RAG_USE_EMBEDDING_V2={rag_config._USE_EMBEDDING_V2}). Check the "
            f"`ai_steps.embedding` model — must be text-embedding-3-large "
            f"(3072) when v2 is on, text-embedding-3-small (1536) when off."
        )


def _build_ts_query(question: str) -> str | None:
    """Tokenise via jieba and produce a `to_tsquery('simple', ...)` string.

    Strips pure-punctuation tokens and single-character non-CJK tokens. Joins
    remaining tokens with ` & `. Returns None when nothing usable is left.
    """
    tokens = tokenizer.tokenize(question)
    show_name_terms = tokenizer.get_show_name_terms()
    cleaned: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if re.fullmatch(r"\W+", tok):
            continue
        # tsquery operators: escape `&|!()<:>`
        tok = re.sub(r"[&|!()<:>\\]", " ", tok).strip()
        if not tok:
            continue
        # Drop tokens flagged as show-name in tokenizer_custom_terms — these
        # are too generic to discriminate (e.g. show name appears across
        # every casual mention episode, drowning the actual answer chunk).
        # Embedding side gets the full question text so semantic signal is
        # preserved. Read the flag from rag_config at call time (reload-safe).
        if rag_config._SHOW_NAME_FILTER_ENABLED and tok in show_name_terms:
            continue
        cleaned.append(tok)
    if not cleaned:
        return None
    # OR-join across multi-char tokens. Eval bake-off (this-not-that-cool, k=5,
    # window=30s, 48 items):
    #   v1 ` & ` keep 1-char:  Recall@5 4.76% — lexical CTE empty (collapsed
    #                          to pure semantic baseline)
    #   v2 ` | ` keep 1-char:  Recall@5 3.57% — particles flood lexical pool,
    #                          comprehension drops to 0%, latency 5.5s
    #   v3 ` & ` drop 1-char:  Recall@5 4.76% — STILL lexical-empty: a podcast
    #                          chunk rarely contains all question entities
    #                          simultaneously (instrumented: 0 chunks match
    #                          `節目名 & 這又沒有很屌 & 怎麼` AND query)
    #   v4 ` | ` drop 1-char:  this version — OR over multi-char tokens lets
    #                          lexical actually contribute; ts_rank weighs
    #                          rare matches so entity-dense chunks lift.
    return " | ".join(cleaned)


_TRANSCRIPT_RRF_SQL = """
WITH semantic AS (
    SELECT c.id AS chunk_id,
           ROW_NUMBER() OVER (
               ORDER BY __EMB_LHS_C__ <=> __EMB_RHS__
           ) AS rank_s
    FROM transcript_chunks c
    JOIN transcripts t ON t.id = c.transcript_id
    JOIN episodes e ON e.id = t.episode_id
    WHERE e.show_id = :show_id
      AND t.status = 'completed'
      AND __EMB_NN_C__
      {episode_filter}
      {metadata_filter}
    LIMIT :per_side
),
lexical AS (
    SELECT c.id AS chunk_id,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(c.text_tsvector, to_tsquery('simple', :ts_query)) DESC
           ) AS rank_l
    FROM transcript_chunks c
    JOIN transcripts t ON t.id = c.transcript_id
    JOIN episodes e ON e.id = t.episode_id
    WHERE e.show_id = :show_id
      AND t.status = 'completed'
      AND c.text_tsvector IS NOT NULL
      AND c.text_tsvector @@ to_tsquery('simple', :ts_query)
      {episode_filter}
      {metadata_filter}
    LIMIT :per_side
),
combined AS (
    SELECT COALESCE(s.chunk_id, l.chunk_id) AS chunk_id,
           1.0 / (:rrf_k + COALESCE(s.rank_s, 999))
         + :weight_chunk * 1.0 / (:rrf_k + COALESCE(l.rank_l, 999)) AS rrf_score
    FROM semantic s
    FULL OUTER JOIN lexical l USING (chunk_id)
)
SELECT cb.chunk_id,
       cb.rrf_score,
       c.start_time,
       c.end_time,
       c.text,
       e.id AS episode_id,
       e.title AS episode_title
FROM combined cb
JOIN transcript_chunks c ON c.id = cb.chunk_id
JOIN transcripts t ON t.id = c.transcript_id
JOIN episodes e ON e.id = t.episode_id
ORDER BY cb.rrf_score DESC
LIMIT :k
"""

_TRANSCRIPT_SEMANTIC_ONLY_SQL = """
SELECT c.id AS chunk_id,
       __EMB_LHS_C__ <=> __EMB_RHS__ AS distance,
       c.start_time,
       c.end_time,
       c.text,
       e.id AS episode_id,
       e.title AS episode_title
FROM transcript_chunks c
JOIN transcripts t ON t.id = c.transcript_id
JOIN episodes e ON e.id = t.episode_id
WHERE e.show_id = :show_id
  AND t.status = 'completed'
  AND __EMB_NN_C__
  {episode_filter}
  {metadata_filter}
ORDER BY distance
LIMIT :k
"""

_DESC_RRF_SQL = """
-- prefer-v2 policy: per-episode, if any v2 chunk exists in the queried show,
-- only that episode's v2 chunks enter the pool; episodes without v2 fall
-- back to v1. This recovers Recall@5 lost by chunking-version-coexistence
-- D3's "v1+v2 share one RRF pool" assumption (see
-- `openspec/changes/description-retrieval-prefer-v2/design.md` D1/D2/D4).
WITH semantic AS (
    SELECT d.id AS chunk_id,
           ROW_NUMBER() OVER (
               ORDER BY __EMB_LHS_D__ <=> __EMB_RHS__
           ) AS rank_s
    FROM episode_description_chunks d
    JOIN episodes e ON e.id = d.episode_id
    WHERE e.show_id = :show_id
      AND __EMB_NN_D__
      AND (
        d.chunking_version = 2
        OR d.episode_id NOT IN (
            SELECT d2.episode_id
            FROM episode_description_chunks d2
            JOIN episodes e2 ON e2.id = d2.episode_id
            WHERE e2.show_id = :show_id AND d2.chunking_version = 2
        )
      )
      {episode_filter}
      {metadata_filter}
    LIMIT :per_side
),
lexical AS (
    SELECT d.id AS chunk_id,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(d.text_tsvector, to_tsquery('simple', :ts_query)) DESC
           ) AS rank_l
    FROM episode_description_chunks d
    JOIN episodes e ON e.id = d.episode_id
    WHERE e.show_id = :show_id
      AND d.text_tsvector IS NOT NULL
      AND d.text_tsvector @@ to_tsquery('simple', :ts_query)
      AND (
        d.chunking_version = 2
        OR d.episode_id NOT IN (
            SELECT d2.episode_id
            FROM episode_description_chunks d2
            JOIN episodes e2 ON e2.id = d2.episode_id
            WHERE e2.show_id = :show_id AND d2.chunking_version = 2
        )
      )
      {episode_filter}
      {metadata_filter}
    LIMIT :per_side
),
combined AS (
    SELECT COALESCE(s.chunk_id, l.chunk_id) AS chunk_id,
           1.0 / (:rrf_k + COALESCE(s.rank_s, 999))
         + :weight_desc * 1.0 / (:rrf_k + COALESCE(l.rank_l, 999)) AS rrf_score
    FROM semantic s
    FULL OUTER JOIN lexical l USING (chunk_id)
)
SELECT cb.chunk_id,
       cb.rrf_score,
       d.text,
       d.chunking_version,
       d.chunk_index,
       e.id AS episode_id,
       e.title AS episode_title
FROM combined cb
JOIN episode_description_chunks d ON d.id = cb.chunk_id
JOIN episodes e ON e.id = d.episode_id
ORDER BY cb.rrf_score DESC
LIMIT :k
"""

_DESC_SEMANTIC_ONLY_SQL = """
-- prefer-v2 policy (semantic-only fallback path). See _DESC_RRF_SQL comment.
SELECT d.id AS chunk_id,
       __EMB_LHS_D__ <=> __EMB_RHS__ AS distance,
       d.text,
       d.chunking_version,
       d.chunk_index,
       e.id AS episode_id,
       e.title AS episode_title
FROM episode_description_chunks d
JOIN episodes e ON e.id = d.episode_id
WHERE e.show_id = :show_id
  AND __EMB_NN_D__
  AND (
    d.chunking_version = 2
    OR d.episode_id NOT IN (
        SELECT d2.episode_id
        FROM episode_description_chunks d2
        JOIN episodes e2 ON e2.id = d2.episode_id
        WHERE e2.show_id = :show_id AND d2.chunking_version = 2
    )
  )
  {episode_filter}
  {metadata_filter}
ORDER BY distance
LIMIT :k
"""


# R3.3 Phase 8.3: title-only lexical pool. Episodes table is small (~hundreds
# per show) so a single ts_rank scan is cheap. The semantic side has no
# title-level embedding (we don't embed titles separately); title pool is
# purely lexical and contributes via RRF weighted by `:weight_title`.
_TITLE_LEXICAL_SQL = """
WITH lexical AS (
    SELECT e.id AS episode_id,
           e.title AS episode_title,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(e.title_tsvector, to_tsquery('simple', :ts_query)) DESC
           ) AS rank_l
    FROM episodes e
    WHERE e.show_id = :show_id
      AND e.title_tsvector IS NOT NULL
      AND e.title_tsvector @@ to_tsquery('simple', :ts_query)
      {episode_filter}
      {metadata_filter}
    LIMIT :per_side
)
SELECT episode_id,
       episode_title,
       :weight_title * 1.0 / (:rrf_k + rank_l) AS rrf_score
FROM lexical
ORDER BY rrf_score DESC
LIMIT :k
"""

_ROUTE_EPISODES_SQL = """
-- prefer-v2 + DISTINCT-episode routing. DISTINCT ON ensures each episode
-- contributes only its single closest chunk (k rows = k distinct episodes,
-- not k chunk rows). See design.md D3.
SELECT episode_id
FROM (
    SELECT DISTINCT ON (e.id)
           e.id AS episode_id,
           __EMB_LHS_D__ <=> __EMB_RHS__ AS dist
    FROM episode_description_chunks d
    JOIN episodes e ON e.id = d.episode_id
    WHERE e.show_id = :show_id
      AND __EMB_NN_D__
      AND (
        d.chunking_version = 2
        OR d.episode_id NOT IN (
            SELECT d2.episode_id
            FROM episode_description_chunks d2
            JOIN episodes e2 ON e2.id = d2.episode_id
            WHERE e2.show_id = :show_id AND d2.chunking_version = 2
        )
      )
    ORDER BY e.id, __EMB_LHS_D__ <=> __EMB_RHS__ ASC
) per_ep
ORDER BY dist ASC
LIMIT :k
"""


def _episode_filter_clause(table_alias: str, params: dict, eps: list[uuid.UUID] | None) -> str:
    """Build the optional `AND <alias>.id = ANY(:episode_ids)` clause and bind."""
    if not eps:
        return ""
    params["episode_ids"] = [str(e) for e in eps]
    return f"AND {table_alias}.id = ANY(CAST(:episode_ids AS uuid[]))"


def _metadata_filter_clause(
    table_alias: str,
    params: dict,
    filters: MetadataFilters | None,
) -> str:
    """Build the optional metadata WHERE clause for guests / date_range filters.

    Binds `:metadata_guests`, `:metadata_date_start`, `:metadata_date_end` as
    needed. Returns an empty string when no filter is set (fail-open path).

    Guest semantics: `episodes.guests @> :metadata_guests::jsonb` — JSONB
    containment, so a list `["馬世芳"]` matches any episode whose `guests`
    array contains "馬世芳" (a list of more than one name behaves as AND).
    """
    if filters is None or filters.is_empty():
        return ""
    clauses: list[str] = []
    if filters.guests:
        clauses.append(
            f"{table_alias}.guests @> CAST(:metadata_guests AS jsonb)"
        )
        params["metadata_guests"] = _stdlib_json.dumps(filters.guests)
    if filters.date_range is not None:
        start, end = filters.date_range
        clauses.append(
            f"{table_alias}.published_at BETWEEN "
            ":metadata_date_start AND :metadata_date_end"
        )
        params["metadata_date_start"] = start
        params["metadata_date_end"] = end
    return "AND " + " AND ".join(clauses)

