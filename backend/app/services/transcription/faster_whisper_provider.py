import asyncio
import os
from functools import lru_cache

from faster_whisper import WhisperModel

from app.core.config import settings
from app.services.ai_step_resolver import StepConfig
from app.services.transcription.base import (
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptionSegment,
)


def _normalise_language(value: str | None) -> str | None:
    if not value:
        return None
    return value.split("-")[0].lower()


@lru_cache(maxsize=4)
def _load_model_cached(
    model_size: str, model_dir: str, device: str, compute_type: str
) -> WhisperModel:
    """Cache by (model_size, model_dir) so admin changes are picked up.

    `device` and `compute_type` still come from infra-level env settings
    rather than ai_steps; admins don't typically tune these.
    """
    os.makedirs(model_dir, exist_ok=True)
    return WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
        download_root=model_dir,
    )


class FasterWhisperProvider(TranscriptionProvider):
    name = "faster-whisper"

    def __init__(self, step_config: StepConfig) -> None:
        extra = step_config.extra_config or {}
        self._model_dir = extra.get("model_dir") or settings.faster_whisper_model_dir
        # Whisper-local model size lives in step.model (e.g. "base", "large-v3");
        # fall back to env default if admin left it blank.
        self._model_size = (
            step_config.model or settings.faster_whisper_model_size
        )

    async def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language)

    def _transcribe_sync(
        self, audio_path: str, language: str | None
    ) -> TranscriptionResult:
        model = _load_model_cached(
            self._model_size,
            self._model_dir,
            settings.faster_whisper_device,
            settings.faster_whisper_compute_type,
        )
        segments_iter, info = model.transcribe(
            audio_path,
            language=_normalise_language(language),
            vad_filter=True,
        )

        segments: list[TranscriptionSegment] = []
        text_parts: list[str] = []
        for seg in segments_iter:
            seg_text = seg.text.strip()
            if not seg_text:
                continue
            segments.append(
                TranscriptionSegment(
                    start=float(seg.start),
                    end=float(seg.end),
                    text=seg_text,
                )
            )
            text_parts.append(seg_text)

        detected_language = getattr(info, "language", None)
        return TranscriptionResult(
            text=" ".join(text_parts),
            language=detected_language,
            segments=segments,
        )
