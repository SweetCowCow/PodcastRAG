import logging
import time

from openai import OpenAI, RateLimitError

from app.core.config import settings

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
        try:
            response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
            return [item.embedding for item in response.data]
        except RateLimitError:
            if attempt >= MAX_RETRIES - 1:
                raise
            logger.warning(
                "OpenAI embeddings rate limited (attempt %d/%d); backing off %.1fs",
                attempt + 1,
                MAX_RETRIES,
                delay,
            )
            time.sleep(delay)
            attempt += 1
            delay *= 2
