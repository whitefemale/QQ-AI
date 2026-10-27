"""Mock 多模态 Provider。所有结果均明确标记 is_mock，绝不冒充真实识别。"""

from __future__ import annotations

import hashlib
import re
import struct

from app.adapters.media.base import (
    ASRProvider,
    EmbeddingProvider,
    MediaProcessor,
    OCRProvider,
    RerankerProvider,
    TTSProvider,
    VideoProcessor,
    VisionProvider,
)
from app.schemas.llm import ConnectionTestResult
from app.schemas.media import (
    AudioTranscriptionRequest,
    GeneratedAudio,
    ImageUnderstandRequest,
    MediaInspectRequest,
    MediaInspectResult,
    MediaUnderstandingResult,
    OCRRequest,
    OCRResult,
    RerankItem,
    RerankRequest,
    RerankResult,
    SpeechSynthesisRequest,
    TranscriptResult,
    VideoUnderstandRequest,
)


class MockVisionProvider(VisionProvider):
    provider_id = "mock.vision"
    is_mock = True

    def __init__(self, **kwargs) -> None:
        kwargs.pop("provider_id", None)
        super().__init__(provider_id="mock.vision", name="Mock 视觉理解（模拟）", **kwargs)

    def capabilities(self) -> list[str]:
        return ["image.describe", "image.understand"]

    async def describe_image(self, request: ImageUnderstandRequest) -> MediaUnderstandingResult:
        return MediaUnderstandingResult(
            summary="这是一张模拟图片。当前使用的是 Mock 视觉 Provider，未进行真实识别。",
            provider_id=self.provider_id,
            confidence=0.0,
            warnings=["Mock 结果仅用于流程测试，不代表真实图片内容。"],
            is_mock=True,
        )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, message="Mock 视觉 Provider 已就绪（仅模拟）。", details={"mock": True})


class MockOCRProvider(OCRProvider):
    is_mock = True

    def __init__(self, **kwargs) -> None:
        kwargs.pop("provider_id", None)
        super().__init__(provider_id="mock.ocr", name="Mock OCR（模拟）", **kwargs)

    def capabilities(self) -> list[str]:
        return ["ocr.extract"]

    async def extract_text(self, request: OCRRequest) -> OCRResult:
        return OCRResult(
            text="[Mock OCR 模拟文本] 这不是从真实图片中识别出的内容。",
            language=request.language,
            provider_id=self.provider_id,
            confidence=0.0,
            is_mock=True,
            warnings=["Mock 结果仅用于流程测试。"],
        )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, message="Mock OCR Provider 已就绪（仅模拟）。")


class MockASRProvider(ASRProvider):
    is_mock = True

    def __init__(self, **kwargs) -> None:
        kwargs.pop("provider_id", None)
        super().__init__(provider_id="mock.asr", name="Mock 语音识别（模拟）", **kwargs)

    def capabilities(self) -> list[str]:
        return ["audio.transcribe"]

    async def transcribe(self, request: AudioTranscriptionRequest) -> TranscriptResult:
        return TranscriptResult(
            text="[Mock ASR 模拟转写] 这不是真实语音的识别结果。",
            language=request.language,
            provider_id=self.provider_id,
            confidence=0.0,
            is_mock=True,
            warnings=["Mock 结果仅用于流程测试，不得作为真实语音内容依据。"],
        )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, message="Mock ASR Provider 已就绪（仅模拟）。")


class MockTTSProvider(TTSProvider):
    is_mock = True

    def __init__(self, **kwargs) -> None:
        kwargs.pop("provider_id", None)
        super().__init__(provider_id="mock.tts", name="Mock 语音合成（模拟）", **kwargs)

    def capabilities(self) -> list[str]:
        return ["audio.synthesize"]

    async def synthesize(self, request: SpeechSynthesisRequest) -> GeneratedAudio:
        sample_rate = 24000
        duration = 0.1
        frames = int(sample_rate * duration)
        data = b"\x00\x00" * frames
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(data),
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            sample_rate,
            sample_rate * 2,
            2,
            16,
            b"data",
            len(data),
        )
        return GeneratedAudio(
            data=header + data,
            mime="audio/wav",
            sample_rate=sample_rate,
            duration_seconds=duration,
            provider_id=self.provider_id,
            is_mock=True,
        )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, message="Mock TTS Provider 已就绪（仅模拟）。")


class MockEmbeddingProvider(EmbeddingProvider):
    is_mock = True

    def __init__(self, **kwargs) -> None:
        kwargs.pop("provider_id", None)
        super().__init__(provider_id="mock.embedding", name="Mock Embedding（模拟）", **kwargs)

    def capabilities(self) -> list[str]:
        return ["text.embed"]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([(byte / 255.0) * 2 - 1 for byte in digest[:16]])
        return vectors

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, message="Mock Embedding Provider 已就绪（仅模拟）。")


def _tokens(text: str) -> set[str]:
    """稳定、无外部依赖的分词：英文/数字按词，中文按字符。"""
    lowered = text.lower()
    words = set(re.findall(r"[a-z0-9]+", lowered))
    words.update(char for char in lowered if "一" <= char <= "鿿")
    return words


class MockMediaProcessor(MediaProcessor):
    is_mock = True

    def __init__(self, **kwargs) -> None:
        kwargs.pop("provider_id", None)
        super().__init__(provider_id="mock.media_processor", name="Mock 媒体检查（模拟）", **kwargs)

    def capabilities(self) -> list[str]:
        return ["media.inspect"]

    async def inspect(self, request: MediaInspectRequest) -> MediaInspectResult:
        digest = hashlib.sha256(request.media_ref.encode("utf-8")).hexdigest()
        return MediaInspectResult(
            media_ref=request.media_ref,
            mime=request.mime,
            size_bytes=None,
            sha256=digest,
            media_type=None,
            recognized=False,
            provider_id=self.provider_id,
            confidence=0.0,
            is_mock=True,
            warnings=["Mock 媒体检查未读取真实文件，不产生真实元数据或内容判断。"],
        )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(
            ok=True, message="Mock 媒体检查 Provider 已就绪（仅模拟）。", details={"mock": True}
        )


class MockRerankerProvider(RerankerProvider):
    is_mock = True

    def __init__(self, **kwargs) -> None:
        kwargs.pop("provider_id", None)
        super().__init__(provider_id="mock.reranker", name="Mock 文本重排（模拟）", **kwargs)

    def capabilities(self) -> list[str]:
        return ["text.rerank"]

    async def rerank(self, request: RerankRequest) -> RerankResult:
        query_tokens = _tokens(request.query)
        scored: list[RerankItem] = []
        for index, document in enumerate(request.documents):
            document_tokens = _tokens(document)
            overlap = len(query_tokens & document_tokens)
            score = round(overlap / len(query_tokens), 6) if query_tokens else 0.0
            scored.append(RerankItem(index=index, document=document, score=score))
        # 稳定排序：分数降序，原始顺序升序；不引入随机性。
        scored.sort(key=lambda item: (-item.score, item.index))
        top_n = len(scored) if request.top_n is None else max(0, min(request.top_n, len(scored)))
        return RerankResult(
            items=scored[:top_n],
            provider_id=self.provider_id,
            is_mock=True,
            warnings=["Mock 重排只按词重叠打分，不是语义重排；仅用于流程测试。"],
        )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(
            ok=True, message="Mock 文本重排 Provider 已就绪（仅模拟）。", details={"mock": True}
        )


class MockVideoProcessor(VideoProcessor):
    is_mock = True

    def __init__(self, **kwargs) -> None:
        kwargs.pop("provider_id", None)
        super().__init__(provider_id="mock.video", name="Mock 视频理解（模拟）", **kwargs)

    def capabilities(self) -> list[str]:
        return ["video.describe"]

    async def describe_video(self, request: VideoUnderstandRequest) -> MediaUnderstandingResult:
        return MediaUnderstandingResult(
            summary="这是一段模拟视频。当前使用的是 Mock 视频 Provider，未下载、解码或识别任何真实视频内容。",
            provider_id=self.provider_id,
            confidence=0.0,
            is_mock=True,
            warnings=["Mock 结果仅用于流程测试，不得作为真实视频内容依据。"],
        )

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(
            ok=True, message="Mock 视频理解 Provider 已就绪（仅模拟）。", details={"mock": True}
        )
