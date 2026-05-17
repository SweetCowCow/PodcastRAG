import asyncio
import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time

from openai import OpenAI

from app.core.config import settings
from app.services import api_health
from app.services.ai_step_resolver import AiStepNotConfiguredError, StepConfig
from app.services.exceptions import OversizedAudioError, RemoteAudioPathError
from app.services.transcription.base import (
    TranscriptionProvider,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger(__name__)

_BYTES_PER_MB = 1024 * 1024
# OpenAI Whisper API 單檔 hard limit = 25 MiB（嚴格小於 26214400 bytes 才安全）。
_OPENAI_WHISPER_HARD_LIMIT_BYTES = 25 * 1024 * 1024


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

    def __init__(self, step_config: StepConfig) -> None:
        if not step_config.api_key:
            raise AiStepNotConfiguredError(
                "openai whisper provider requires api_key on ai_steps.transcription"
            )
        self._client = OpenAI(
            base_url=step_config.base_url, api_key=step_config.api_key
        )
        self._model = step_config.model or "whisper-1"

    async def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, audio_path, language)

    def _transcribe_sync(
        self, audio_path: str, language: str | None
    ) -> TranscriptionResult:
        kwargs: dict = {
            "model": self._model,
            "response_format": "verbose_json",
        }
        lang = _normalise_language(language)
        if lang:
            kwargs["language"] = lang

        chunk_size_bytes = settings.openai_whisper_chunk_size_mb * _BYTES_PER_MB

        # ── Task 2.2：偵測非本地 path（譬如 R2 presigned URL）並 raise typed exception
        # worker 層應 catch RemoteAudioPathError 後重新下載到本地 temp 檔再 retry。
        if (
            isinstance(audio_path, str)
            and (
                audio_path.startswith("http://")
                or audio_path.startswith("https://")
                or not os.path.isabs(audio_path)
            )
        ):
            logger.error(
                "openai_whisper_remote_audio_path audio_path=%s",
                audio_path,
            )
            raise RemoteAudioPathError(
                f"_transcribe_sync requires a local absolute file path, got: {audio_path}"
            )
        if not os.path.exists(audio_path):
            logger.error(
                "openai_whisper_missing_audio_file audio_path=%s",
                audio_path,
            )
            raise RemoteAudioPathError(
                f"_transcribe_sync audio_path does not exist locally: {audio_path}"
            )

        file_size = os.path.getsize(audio_path)

        # ── Task 1.1：進場 INFO log 印 chunking decision 相關欄位
        logger.info(
            "openai_whisper_transcribe_start "
            "audio_basename=%s exists=%s size_bytes=%d "
            "chunk_size_mb=%s chunk_size_bytes=%d",
            os.path.basename(audio_path),
            True,
            file_size,
            settings.openai_whisper_chunk_size_mb,
            chunk_size_bytes,
        )

        if file_size <= chunk_size_bytes:
            # ── Task 2.3：上傳前 hard limit guard（25 MiB）
            if file_size > _OPENAI_WHISPER_HARD_LIMIT_BYTES:
                logger.error(
                    "openai_whisper_oversized_single_file size_bytes=%d limit_bytes=%d "
                    "audio_basename=%s",
                    file_size,
                    _OPENAI_WHISPER_HARD_LIMIT_BYTES,
                    os.path.basename(audio_path),
                )
                raise OversizedAudioError(
                    f"audio file {os.path.basename(audio_path)} is {file_size} bytes, "
                    f"exceeds OpenAI Whisper 25 MiB hard limit "
                    f"({_OPENAI_WHISPER_HARD_LIMIT_BYTES} bytes). "
                    f"Lower openai_whisper_chunk_size_mb (<=25) to force chunking."
                )
            logger.info(
                "openai_whisper_decision decision=single chunks=1 "
                "audio_basename=%s",
                os.path.basename(audio_path),
            )
            with open(audio_path, "rb") as f:
                response = self._call_with_tracker(file=f, **kwargs)
            return _response_to_result(response, offset_seconds=0.0)

        tempdir = tempfile.mkdtemp(prefix="whisper_chunks_")
        try:
            chunks = _split_audio(audio_path, chunk_size_bytes, tempdir)

            logger.info(
                "openai_whisper_decision decision=chunked chunks=%d "
                "audio_basename=%s",
                len(chunks),
                os.path.basename(audio_path),
            )

            merged_segments: list[TranscriptionSegment] = []
            merged_texts: list[str] = []
            merged_language: str | None = None

            for chunk_path, offset_seconds in chunks:
                # ── Task 2.3：每個 chunk 上傳前再 size guard 一次
                chunk_size = os.path.getsize(chunk_path)
                if chunk_size > _OPENAI_WHISPER_HARD_LIMIT_BYTES:
                    logger.error(
                        "openai_whisper_oversized_chunk chunk=%s size_bytes=%d "
                        "limit_bytes=%d",
                        os.path.basename(chunk_path),
                        chunk_size,
                        _OPENAI_WHISPER_HARD_LIMIT_BYTES,
                    )
                    raise OversizedAudioError(
                        f"chunk {os.path.basename(chunk_path)} is {chunk_size} bytes, "
                        f"exceeds OpenAI Whisper 25 MiB hard limit "
                        f"({_OPENAI_WHISPER_HARD_LIMIT_BYTES} bytes). "
                        f"Lower openai_whisper_chunk_size_mb to a safer value."
                    )
                with open(chunk_path, "rb") as f:
                    response = self._call_with_tracker(file=f, **kwargs)
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

    def _call_with_tracker(self, **kwargs):
        start_ns = time.monotonic_ns()
        try:
            response = self._client.audio.transcriptions.create(**kwargs)
        except Exception as exc:
            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
            http_status = getattr(exc, "status_code", None)
            api_health.record(
                "openai_whisper",
                ok=False,
                duration_ms=duration_ms,
                error_category=api_health.classify_error(exc, http_status),
                http_status=http_status,
            )
            raise
        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        api_health.record(
            "openai_whisper",
            ok=True,
            duration_ms=duration_ms,
            http_status=200,
        )
        return response


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
