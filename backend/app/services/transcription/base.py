from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranscriptionSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptionResult:
    text: str
    language: str | None
    segments: list[TranscriptionSegment]


class TranscriptionProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(
        self, audio_path: str, language: str | None = None
    ) -> TranscriptionResult:
        raise NotImplementedError
