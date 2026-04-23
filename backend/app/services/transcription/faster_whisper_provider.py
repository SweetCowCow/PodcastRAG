import asyncio
import os
from functools import lru_cache

from faster_whisper import WhisperModel

from app.core.config import settings
from app.services.transcription.base import (
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptionSegment,
)


def _normalise_language(value: str | None) -> str | None:
    if not value:
        return None
    return value.split("-")[0].lower()


@lru_cache(maxsize=1)
def _load_model() -> WhisperModel:
    os.makedirs(settings.faster_whisper_model_dir, exist_ok=True)
    return WhisperModel(
        settings.faster_whisper_model_size,
        device=settings.faster_whisper_device,
        compute_type=settings.faster_whisper_compute_type,
        download_root=settings.faster_whisper_model_dir,
    )


class FasterWhisperProvider(TranscriptionProvider):
    name = "faster-whisper"

    async def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language)

    def _transcribe_sync(
        self, audio_path: str, language: str | None
    ) -> TranscriptionResult:
        model = _load_model()
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
