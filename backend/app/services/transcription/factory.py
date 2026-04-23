from functools import lru_cache

from app.core.config import settings
from app.services.transcription.base import TranscriptionProvider

SUPPORTED_PROVIDERS = ("openai", "faster-whisper")


@lru_cache(maxsize=1)
def get_provider() -> TranscriptionProvider:
    name = (settings.transcription_provider or "").lower()
    if name == "openai":
        from app.services.transcription.openai_provider import OpenAIWhisperProvider

        return OpenAIWhisperProvider()
    if name == "faster-whisper":
        from app.services.transcription.faster_whisper_provider import (
            FasterWhisperProvider,
        )

        return FasterWhisperProvider()
    raise RuntimeError(
        f"未知的 TRANSCRIPTION_PROVIDER='{settings.transcription_provider}'，"
        f"僅支援：{', '.join(SUPPORTED_PROVIDERS)}"
    )
