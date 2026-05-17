"""Unit tests for OpenAIWhisperProvider chunking + size guards.

Covers tasks 3.1 / 3.2 / 3.3 of whisper-chunking-fix change.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.ai_step_resolver import StepConfig
from app.services.exceptions import OversizedAudioError, RemoteAudioPathError
from app.services.transcription import openai_provider as op
from app.services.transcription.openai_provider import OpenAIWhisperProvider


def _make_provider() -> OpenAIWhisperProvider:
    cfg = StepConfig(
        step_key="transcription",
        step_type="whisper",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="whisper-1",
        extra_config={},
    )
    # Patch OpenAI client constructor so we don't hit network on init.
    with patch.object(op, "OpenAI", return_value=MagicMock()):
        return OpenAIWhisperProvider(cfg)


def _fake_response(text: str = "hi", language: str = "zh"):
    """Return an object mimicking openai response.model_dump()."""
    obj = MagicMock()
    obj.model_dump.return_value = {
        "text": text,
        "language": language,
        "segments": [],
    }
    return obj


def _write_file(path: str, size_bytes: int) -> None:
    """Write a sparse file of exactly `size_bytes` bytes."""
    with open(path, "wb") as f:
        if size_bytes > 0:
            f.seek(size_bytes - 1)
            f.write(b"\0")


# ─── Task 3.1: 26.4 MB file triggers _split_audio with >=2 chunks ───

def test_oversized_file_triggers_split_audio_with_multiple_chunks(tmp_path):
    """A 26.4 MB file (above default 22 MiB chunk threshold but each chunk
    must stay <= chunk_size_bytes) should be split into >=2 chunks via
    _split_audio, and every produced chunk must be <= chunk_size_bytes."""
    audio_path = str(tmp_path / "big.mp3")
    file_size = int(26.4 * 1024 * 1024)  # 26.4 MB
    _write_file(audio_path, file_size)

    provider = _make_provider()

    # Force chunk_size_mb=22 (= 23068672 bytes) so file > chunk_size_bytes.
    fake_settings = SimpleNamespace(openai_whisper_chunk_size_mb=22)

    captured: dict = {}

    def fake_split_audio(path, chunk_size_bytes, tempdir):
        # Simulate ffmpeg producing 2 small chunks (we don't actually need ffmpeg).
        captured["called"] = True
        captured["chunk_size_bytes"] = chunk_size_bytes
        chunks = []
        chunk_sizes = []
        chunk_bytes = chunk_size_bytes - 1024  # under the limit
        for i in range(2):
            cp = os.path.join(tempdir, f"chunk_{i:03d}.mp3")
            _write_file(cp, chunk_bytes)
            chunks.append((cp, float(i) * 100.0))
            chunk_sizes.append(chunk_bytes)
        captured["chunks"] = chunks
        captured["chunk_sizes"] = chunk_sizes
        return chunks

    with patch.object(op, "settings", fake_settings), patch.object(
        op, "_split_audio", side_effect=fake_split_audio
    ):
        provider._client.audio.transcriptions.create = MagicMock(
            return_value=_fake_response()
        )
        result = provider._transcribe_sync(audio_path, language=None)

    assert captured.get("called") is True, "_split_audio must be invoked"
    assert len(captured["chunks"]) >= 2
    # Use the size captured at creation time (tempdir is cleaned up in
    # _transcribe_sync's finally block before we get here).
    for size in captured["chunk_sizes"]:
        assert size <= captured["chunk_size_bytes"]
    # 2 chunks → 2 HTTP calls
    assert provider._client.audio.transcriptions.create.call_count == 2
    assert result is not None


# ─── Task 3.2: OversizedAudioError when single file > 25 MiB hard limit ───

def test_oversized_single_file_raises_and_skips_http(tmp_path):
    """26214401 bytes (just over 25 MiB) must raise OversizedAudioError
    BEFORE any HTTP call, when chunk_size_mb is set high enough that the
    chunking branch is not entered."""
    audio_path = str(tmp_path / "oversize.mp3")
    _write_file(audio_path, 26_214_401)  # 25 MiB + 1

    provider = _make_provider()
    # chunk_size_mb=30 → chunk_size_bytes = 31457280, so file (26214401)
    # <= chunk_size_bytes → single-upload branch → hard-limit guard fires.
    fake_settings = SimpleNamespace(openai_whisper_chunk_size_mb=30)

    provider._client.audio.transcriptions.create = MagicMock(
        return_value=_fake_response()
    )

    with patch.object(op, "settings", fake_settings):
        with pytest.raises(OversizedAudioError):
            provider._transcribe_sync(audio_path, language=None)

    provider._client.audio.transcriptions.create.assert_not_called()


# ─── Task 3.3: RemoteAudioPathError when audio_path is an http(s) URL ───

def test_remote_audio_path_raises_before_any_io():
    """audio_path starting with https:// must raise RemoteAudioPathError
    without touching the filesystem or making any HTTP request."""
    provider = _make_provider()
    provider._client.audio.transcriptions.create = MagicMock(
        return_value=_fake_response()
    )

    with pytest.raises(RemoteAudioPathError):
        provider._transcribe_sync(
            "https://r2.example.com/audio/EP20.mp3?sig=abc", language=None
        )

    provider._client.audio.transcriptions.create.assert_not_called()


def test_http_audio_path_raises():
    provider = _make_provider()
    provider._client.audio.transcriptions.create = MagicMock(
        return_value=_fake_response()
    )
    with pytest.raises(RemoteAudioPathError):
        provider._transcribe_sync(
            "http://example.com/a.mp3", language=None
        )
    provider._client.audio.transcriptions.create.assert_not_called()
