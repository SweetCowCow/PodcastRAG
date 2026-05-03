import logging
import time

from openai import OpenAI, RateLimitError

from app.services import api_health
from app.services.ai_step_resolver import StepConfig

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 64
MAX_RETRIES = 3


def embed_texts(texts: list[str], step_config: StepConfig) -> list[list[float]]:
    """Embed via the configured `embedding` step.

    The caller is responsible for resolving the StepConfig (via
    `services.ai_step_resolver.get_step_config('embedding')`) and passing
    it in. Embedding always uses OpenAI official; the admin UI plus backend
    validator (D4) keep the underlying api_key constrained to provider=openai.
    """
    if not texts:
        return []

    client = OpenAI(base_url=step_config.base_url, api_key=step_config.api_key)
    all_vectors: list[list[float]] = []

    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        vectors = _embed_with_retry(client, batch, step_config.model)
        all_vectors.extend(vectors)

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
