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
    MediaInspectRequest,
    MediaInspectResult,
    MediaMetadata,
    MediaUnderstandingResult,
    OCRRequest,
    OCRResult,
    RerankRequest,
    RerankResult,
    SpeechSynthesisRequest,
    StoredMediaRef,
    TranscriptResult,
    VideoUnderstandRequest,
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


class MediaProcessor(BaseMediaProvider):
    """媒体检查/元数据解析。只读取内部 media_ref，不接受外部 URL。"""

    provider_type = "media_processor"

    @abstractmethod
    async def inspect(self, request: MediaInspectRequest) -> MediaInspectResult:
        raise NotImplementedError


class RerankerProvider(BaseMediaProvider):
    """文本重排。当前仅建立契约与 Mock，不接入记忆检索。"""

    provider_type = "reranker"

    @abstractmethod
    async def rerank(self, request: RerankRequest) -> RerankResult:
        raise NotImplementedError


class VideoProcessor(BaseMediaProvider):
    """视频理解。当前仅建立契约与 Mock，不做下载、解码或转码。"""

    provider_type = "video"

    @abstractmethod
    async def describe_video(self, request: VideoUnderstandRequest) -> MediaUnderstandingResult:
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
