import logging
import time

from openai import OpenAI, RateLimitError

from app.core.config import settings
from app.services import api_health

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 64
MAX_RETRIES = 3


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Call OpenAI embeddings API in batches of 64, preserving input order.

    Always hits the official OpenAI endpoint (not the Zeabur AI Hub),
    since the hub only proxies chat/completions.
    """
    if not texts:
        return []

    client = OpenAI(api_key=settings.openai_api_key)
    all_vectors: list[list[float]] = []

    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        vectors = _embed_with_retry(client, batch)
        all_vectors.extend(vectors)

    return all_vectors


def _embed_with_retry(client: OpenAI, batch: list[str]) -> list[list[float]]:
    attempt = 0
    delay = 1.0
    while True:
        start_ns = time.monotonic_ns()
        try:
            response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
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
