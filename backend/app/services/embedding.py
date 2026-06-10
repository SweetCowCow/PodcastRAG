import logging
import os
import time

from openai import OpenAI, RateLimitError

from app.services import api_health, rag_cache
from app.services.ai_step_resolver import StepConfig

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 64
MAX_RETRIES = 3

# r3-4: dual-write transition. While EMBEDDING_DUAL_WRITE is true, write
# paths (transcript chunk embed + description chunk embed) call BOTH the
# legacy small-model embedder AND the v2 large-model embedder, populating
# `embedding` (1536) and `embedding_v2` (3072) respectively.
#
# Fixed model names — intentionally NOT pulled from `ai_steps` so the
# dual-write contract stays deterministic regardless of how ai_steps is
# flipped during cutover (Section 7). The step_config arg supplies only
# base_url + api_key (the OpenAI provider).
LEGACY_EMBEDDING_MODEL = "text-embedding-3-small"
V2_EMBEDDING_MODEL = "text-embedding-3-large"
V2_EMBEDDING_DIM = 3072


def _dual_write_enabled() -> bool:
    raw = os.getenv("EMBEDDING_DUAL_WRITE", "true").strip().lower()
    return raw not in ("false", "0", "off", "")


def embed_texts(texts: list[str], step_config: StepConfig) -> list[list[float]]:
    """Embed via the configured `embedding` step.

    The caller is responsible for resolving the StepConfig (via
    `services.ai_step_resolver.get_step_config('embedding')`) and passing
    it in. Embedding always uses OpenAI official; the admin UI plus backend
    validator (D4) keep the underlying api_key constrained to provider=openai.
    """
    if not texts:
        return []

    # r4-rag-result-cache: cache single-query embeddings. The query paths
    # (semantic /search + chat agent tool searches) all embed one string at a
    # time; batch write-time embeds (transcription) are left uncached.
    if len(texts) == 1:
        cached = rag_cache.get_embedding(texts[0], step_config.model)
        if cached is not None:
            return [cached]

    client = OpenAI(base_url=step_config.base_url, api_key=step_config.api_key)
    all_vectors: list[list[float]] = []

    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        vectors = _embed_with_retry(client, batch, step_config.model)
        all_vectors.extend(vectors)

    if len(texts) == 1 and all_vectors:
        rag_cache.set_embedding(texts[0], step_config.model, all_vectors[0])

    return all_vectors


def _embed_with_retry(
    client: OpenAI, batch: list[str], model: str
) -> list[list[float]]:
    attempt = 0
    delay = 1.0
    while True:
        start_ns = time.monotonic_ns()
        try:
            response = client.embeddings.create(model=model, input=batch)
        except Exception as exc:
            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            http_status = getattr(exc, "status_code", None)
            api_health.record(
                "openai_embedding",
                ok=False,
                duration_ms=duration_ms,
                error_category=api_health.classify_error(exc, http_status),
                http_status=http_status,
            )
            if isinstance(exc, RateLimitError) and attempt < MAX_RETRIES - 1:
                logger.warning(
                    "OpenAI embeddings rate limited (attempt %d/%d); backing off %.1fs",
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
                attempt += 1
                delay *= 2
                continue
            raise
        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        api_health.record(
            "openai_embedding",
            ok=True,
            duration_ms=duration_ms,
            http_status=200,
        )
        return [item.embedding for item in response.data]


def embed_texts_v2(texts: list[str], step_config: StepConfig) -> list[list[float]]:
    """Embed `texts` with the v2 model (`text-embedding-3-large`, dim=3072).

    Uses `step_config.base_url` + `step_config.api_key` only; model is
    pinned to `V2_EMBEDDING_MODEL` regardless of what ai_steps says. This
    lets the dual-write path keep populating `embedding_v2` even after
    ai_steps is flipped to v3-large for query-time embedding.
    """
    if not texts:
        return []

    client = OpenAI(base_url=step_config.base_url, api_key=step_config.api_key)
    all_vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        vectors = _embed_with_retry(client, batch, V2_EMBEDDING_MODEL)
        all_vectors.extend(vectors)
    return all_vectors


def embed_texts_dual(
    texts: list[str], step_config: StepConfig
) -> tuple[list[list[float]] | None, list[list[float]] | None]:
    """Dual-write helper: returns (legacy_vectors, v2_vectors).

    During the r3-4 transition `EMBEDDING_DUAL_WRITE=true` (default) keeps
    both columns populated. Either side may be None on per-side failure;
    callers SHALL still insert the row with the successful side populated
    (spec Scenario "dual-write during transition").

    When `EMBEDDING_DUAL_WRITE=false`, only the v2 column is populated and
    the legacy slot is returned as None. Callers MUST NOT write the legacy
    column when None is returned for that side.
    """
    if not texts:
        return [], []

    legacy_vecs: list[list[float]] | None = None
    v2_vecs: list[list[float]] | None = None
    dual = _dual_write_enabled()

    if dual:
        try:
            client = OpenAI(
                base_url=step_config.base_url, api_key=step_config.api_key
            )
            legacy_vecs = []
            for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
                batch = texts[start : start + EMBEDDING_BATCH_SIZE]
                legacy_vecs.extend(
                    _embed_with_retry(client, batch, LEGACY_EMBEDDING_MODEL)
                )
        except Exception:
            logger.exception("dual-write legacy embed failed; v2 still attempted")
            legacy_vecs = None

    try:
        v2_vecs = embed_texts_v2(texts, step_config)
    except Exception:
        logger.exception("dual-write v2 embed failed; legacy retained if present")
        v2_vecs = None

    return legacy_vecs, v2_vecs
