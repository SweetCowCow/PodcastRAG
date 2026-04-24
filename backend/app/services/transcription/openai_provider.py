import asyncio
import json
import math
import os
import shutil
import subprocess
import tempfile

from openai import OpenAI

from app.core.config import settings
from app.services.transcription.base import (
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptionSegment,
)

_BYTES_PER_MB = 1024 * 1024


def _normalise_language(value: str | None) -> str | None:
    if not value:
        return None
    # Whisper API 接受 ISO-639-1 兩字母代碼。zh-tw 需截成 zh。
    return value.split("-")[0].lower()


def _probe_duration_seconds(audio_path: str) -> float:
    """用 ffprobe 讀取音檔 duration（只讀 metadata，不 decode）。"""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            audio_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed ({result.returncode}): {result.stderr.strip()}"
        )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _split_audio(
    audio_path: str, chunk_size_bytes: int, tempdir: str
) -> list[tuple[str, float]]:
    """把音訊按時間平分成數段 mp3，寫入 `tempdir`。

    使用 ffmpeg stream copy（`-c copy`），不 decode 也不 re-encode，
    記憶體使用常數（< 100 MB）不隨音檔長度增加。
    切點對齊到最近的 MP3 frame，誤差 ±1~2 秒。

    回傳 `[(chunk_path, start_offset_seconds), ...]`。start_offset 是
    請求給 ffmpeg 的 `-ss` 值（非實際 keyframe 對齊後位置），以維持
    segment offset merging 的時間軸連續性。呼叫端負責建立與清理 tempdir。
    """
    total_bytes = os.path.getsize(audio_path)
    chunk_count = math.ceil(total_bytes / chunk_size_bytes)

    total_duration = _probe_duration_seconds(audio_path)
    chunk_duration = total_duration / chunk_count

    chunks: list[tuple[str, float]] = []
    for i in range(chunk_count):
        start = i * chunk_duration
        chunk_path = os.path.join(tempdir, f"chunk_{i:03d}.mp3")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{start:.3f}",
                "-t", f"{chunk_duration:.3f}",
                "-i", audio_path,
                "-c", "copy",
                chunk_path,
            ],
            check=True,
        )
        chunks.append((chunk_path, start))
    return chunks


class OpenAIWhisperProvider(TranscriptionProvider):
    name = "openai"

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("使用 openai provider 需要設定 OPENAI_API_KEY")
        self._client = OpenAI(api_key=settings.openai_api_key)

    async def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language)

    def _transcribe_sync(
        self, audio_path: str, language: str | None
    ) -> TranscriptionResult:
        kwargs: dict = {
            "model": "whisper-1",
            "response_format": "verbose_json",
        }
        lang = _normalise_language(language)
        if lang:
            kwargs["language"] = lang

        chunk_size_bytes = settings.openai_whisper_chunk_size_mb * _BYTES_PER_MB
        if os.path.getsize(audio_path) <= chunk_size_bytes:
            with open(audio_path, "rb") as f:
                response = self._client.audio.transcriptions.create(file=f, **kwargs)
            return _response_to_result(response, offset_seconds=0.0)

        tempdir = tempfile.mkdtemp(prefix="whisper_chunks_")
        try:
            chunks = _split_audio(audio_path, chunk_size_bytes, tempdir)

            merged_segments: list[TranscriptionSegment] = []
            merged_texts: list[str] = []
            merged_language: str | None = None

            for chunk_path, offset_seconds in chunks:
                with open(chunk_path, "rb") as f:
                    response = self._client.audio.transcriptions.create(
                        file=f, **kwargs
                    )
                partial = _response_to_result(response, offset_seconds=offset_seconds)
                merged_segments.extend(partial.segments)
                if partial.text:
                    merged_texts.append(partial.text)
                if merged_language is None and partial.language:
                    merged_language = partial.language

            return TranscriptionResult(
                text=" ".join(merged_texts),
                language=merged_language,
                segments=merged_segments,
            )
        finally:
            shutil.rmtree(tempdir, ignore_errors=True)


def _response_to_result(response, offset_seconds: float) -> TranscriptionResult:
    data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    segments_raw = data.get("segments") or []
    segments = [
        TranscriptionSegment(
            start=float(seg.get("start", 0.0)) + offset_seconds,
            end=float(seg.get("end", 0.0)) + offset_seconds,
            text=(seg.get("text") or "").strip(),
        )
        for seg in segments_raw
    ]
    return TranscriptionResult(
        text=(data.get("text") or "").strip(),
        language=data.get("language"),
        segments=segments,
    )
