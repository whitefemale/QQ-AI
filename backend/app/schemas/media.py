"""多模态 Provider 请求 / 结果 DTO。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MediaUnderstandingResult(BaseModel):
    summary: str = ""
    transcript: str = ""
    ocr_text: str = ""
    detected_language: str | None = None
    timestamps: list[dict[str, Any]] = Field(default_factory=list)
    provider_id: str | None = None
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    is_mock: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class ImageUnderstandRequest(BaseModel):
    media_ref: str
    mime: str | None = None
    prompt: str | None = None
    language: str = "zh"


class OCRRequest(BaseModel):
    media_ref: str
    mime: str | None = None
    language: str = "chi_sim"


class OCRResult(BaseModel):
    text: str
    language: str | None = None
    provider_id: str | None = None
    confidence: float | None = None
    is_mock: bool = False
    warnings: list[str] = Field(default_factory=list)


class AudioTranscriptionRequest(BaseModel):
    media_ref: str
    mime: str | None = None
    language: str | None = "zh"


class TranscriptResult(BaseModel):
    text: str
    language: str | None = None
    timestamps: list[dict[str, Any]] = Field(default_factory=list)
    provider_id: str | None = None
    confidence: float | None = None
    is_mock: bool = False
    warnings: list[str] = Field(default_factory=list)


class SpeechSynthesisRequest(BaseModel):
    text: str
    voice: str | None = None
    language: str = "zh"
    speed: float = 1.0


class GeneratedAudio(BaseModel):
    data: bytes
    mime: str = "audio/wav"
    sample_rate: int = 24000
    duration_seconds: float | None = None
    provider_id: str | None = None
    is_mock: bool = False


class BinarySource:
    """媒体二进制输入的轻量包装，避免业务层依赖供应商临时 URL。"""

    def __init__(self, data: bytes, mime: str | None = None, filename: str | None = None) -> None:
        self.data = data
        self.mime = mime
        self.filename = filename


class StoredMediaRef(BaseModel):
    media_ref: str
    mime: str | None = None
    size_bytes: int = 0
    sha256: str


class MediaMetadata(BaseModel):
    account_id: str | None = None
    group_id: str | None = None
    media_type: str = "file"
    mime: str | None = None
    source_message_id: str | None = None
    filename: str | None = None
