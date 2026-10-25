"""多模态 Provider 协议，供应商中立。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.schemas.llm import ConnectionTestResult
from app.schemas.media import (
    AudioTranscriptionRequest,
    BinarySource,
    GeneratedAudio,
    ImageUnderstandRequest,
    MediaMetadata,
    MediaUnderstandingResult,
    OCRRequest,
    OCRResult,
    SpeechSynthesisRequest,
    StoredMediaRef,
    TranscriptResult,
)


class BaseMediaProvider(ABC):
    provider_type: str = "base"
    is_mock: bool = False

    def __init__(
        self,
        *,
        provider_id: str,
        name: str,
        version: str = "1.0.0",
        config: dict[str, Any] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.name = name
        self.version = version
        self.config = config or {}

    @abstractmethod
    def capabilities(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(self) -> ConnectionTestResult:
        raise NotImplementedError


class VisionProvider(BaseMediaProvider):
    provider_type = "vision"

    @abstractmethod
    async def describe_image(self, request: ImageUnderstandRequest) -> MediaUnderstandingResult:
        raise NotImplementedError


class OCRProvider(BaseMediaProvider):
    provider_type = "ocr"

    @abstractmethod
    async def extract_text(self, request: OCRRequest) -> OCRResult:
        raise NotImplementedError


class ASRProvider(BaseMediaProvider):
    provider_type = "asr"

    @abstractmethod
    async def transcribe(self, request: AudioTranscriptionRequest) -> TranscriptResult:
        raise NotImplementedError


class TTSProvider(BaseMediaProvider):
    provider_type = "tts"

    @abstractmethod
    async def synthesize(self, request: SpeechSynthesisRequest) -> GeneratedAudio:
        raise NotImplementedError


class EmbeddingProvider(BaseMediaProvider):
    provider_type = "embedding"

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class MediaStore(ABC):
    @abstractmethod
    async def put(self, source: BinarySource, metadata: MediaMetadata) -> StoredMediaRef:
        raise NotImplementedError

    @abstractmethod
    async def get(self, media_ref: str) -> BinarySource:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, media_ref: str) -> None:
        raise NotImplementedError
