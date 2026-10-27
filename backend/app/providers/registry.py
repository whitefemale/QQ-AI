"""统一能力注册表：Provider 的能力、版本、健康状态与启用状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.adapters.media.base import BaseMediaProvider
from app.adapters.media.mock import (
    MockASRProvider,
    MockEmbeddingProvider,
    MockMediaProcessor,
    MockOCRProvider,
    MockRerankerProvider,
    MockTTSProvider,
    MockVideoProcessor,
    MockVisionProvider,
)
from app.core.errors import AppError, ErrorCode
from app.core.time import iso_utc, utcnow

CAPABILITY_TYPES: dict[str, str] = {
    "image.describe": "vision",
    "image.understand": "vision",
    "ocr.extract": "ocr",
    "audio.transcribe": "asr",
    "audio.synthesize": "tts",
    "text.embed": "embedding",
    # 以下能力当前只有接口契约与 Mock，不接入聊天流水线。
    "media.inspect": "media_processor",
    "text.rerank": "reranker",
    "video.describe": "video",
}


@dataclass
class RegistryEntry:
    provider_id: str
    provider_type: str
    name: str
    version: str = "1.0.0"
    capabilities: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)
    enabled: bool = False
    status: str = "unconfigured"
    health_status: str = "unknown"
    is_mock: bool = False
    planned: bool = False
    provider: BaseMediaProvider | None = None
    last_error: str | None = None
    last_health_check_at: datetime | None = None
    limits: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "name": self.name,
            "version": self.version,
            "capabilities": self.capabilities,
            "config_schema": self.config_schema,
            "enabled": self.enabled,
            "status": self.status,
            "health_status": self.health_status,
            "is_mock": self.is_mock,
            "planned": self.planned,
            "last_error": self.last_error,
            "last_health_check_at": iso_utc(self.last_health_check_at),
            "limits": self.limits,
        }


class ProviderRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry] = {}

    def register(self, entry: RegistryEntry) -> None:
        self._entries[entry.provider_id] = entry

    def register_provider(
        self,
        provider: BaseMediaProvider,
        *,
        enabled: bool = False,
        config_schema: dict[str, Any] | None = None,
    ) -> None:
        self.register(
            RegistryEntry(
                provider_id=provider.provider_id,
                provider_type=provider.provider_type,
                name=provider.name,
                version=provider.version,
                capabilities=provider.capabilities(),
                config_schema=config_schema or {},
                enabled=enabled,
                status="disabled" if not enabled else "available",
                health_status="unknown",
                is_mock=provider.is_mock,
                provider=provider,
            )
        )

    def register_planned(
        self,
        provider_id: str,
        provider_type: str,
        name: str,
        capabilities: list[str],
    ) -> None:
        self.register(
            RegistryEntry(
                provider_id=provider_id,
                provider_type=provider_type,
                name=name,
                capabilities=capabilities,
                enabled=False,
                status="planned",
                health_status="unknown",
                planned=True,
            )
        )

    def get(self, provider_id: str) -> RegistryEntry | None:
        return self._entries.get(provider_id)

    def require(self, provider_id: str) -> RegistryEntry:
        entry = self.get(provider_id)
        if entry is None:
            raise AppError(ErrorCode.PROVIDER_NOT_FOUND, "Provider 不存在。", status_code=404)
        return entry

    def list_entries(self, provider_type: str | None = None) -> list[RegistryEntry]:
        entries = list(self._entries.values())
        if provider_type:
            entries = [entry for entry in entries if entry.provider_type == provider_type]
        return sorted(entries, key=lambda item: (item.planned, item.is_mock, item.provider_id))

    def set_enabled(self, provider_id: str, enabled: bool) -> RegistryEntry:
        entry = self.require(provider_id)
        if entry.planned or entry.provider is None:
            raise AppError(
                ErrorCode.PROVIDER_CAPABILITY_MISSING,
                "该 Provider 尚未实现，不能启用。",
                status_code=400,
            )
        entry.enabled = enabled
        entry.status = "available" if enabled else "disabled"
        return entry

    async def health_check(self, provider_id: str) -> RegistryEntry:
        entry = self.require(provider_id)
        if entry.provider is None:
            entry.health_status = "unavailable"
            entry.last_error = "该 Provider 尚未实现。"
            return entry
        if not entry.enabled:
            entry.health_status = "disabled"
            entry.last_health_check_at = utcnow()
            return entry
        try:
            result = await entry.provider.test_connection()
            entry.health_status = "healthy" if result.ok else "unhealthy"
            entry.status = "available" if result.ok else "error"
            entry.last_error = None if result.ok else result.message
        except AppError as exc:
            entry.health_status = "unhealthy"
            entry.status = "error"
            entry.last_error = exc.message
        entry.last_health_check_at = utcnow()
        return entry

    def available_for(self, capability: str) -> list[BaseMediaProvider]:
        """按能力返回已启用 Provider，真实 Provider 优先于 Mock。"""
        provider_type = CAPABILITY_TYPES.get(capability)
        candidates = [
            entry
            for entry in self._entries.values()
            if entry.enabled
            and entry.provider is not None
            and entry.health_status != "unhealthy"
            and (capability in entry.capabilities or entry.provider_type == provider_type)
        ]
        candidates.sort(key=lambda item: (item.is_mock, item.provider_id))
        return [entry.provider for entry in candidates if entry.provider is not None]

    def capability_status(self) -> list[dict[str, Any]]:
        return [entry.public() for entry in self.list_entries()]


def build_default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    for provider in (
        MockVisionProvider(),
        MockOCRProvider(),
        MockASRProvider(),
        MockTTSProvider(),
        MockEmbeddingProvider(),
        MockMediaProcessor(),
        MockRerankerProvider(),
        MockVideoProcessor(),
    ):
        registry.register_provider(
            provider,
            enabled=False,
            config_schema={
                "type": "object",
                "properties": {"mock_note": {"type": "string", "readOnly": True}},
                "description": "Mock Provider 仅用于流程测试，不进行真实识别。",
            },
        )
    registry.register_planned("planned.vision", "vision", "真实视觉理解 Provider（未配置）", ["image.describe"])
    registry.register_planned("planned.ocr", "ocr", "真实 OCR Provider（未配置）", ["ocr.extract"])
    registry.register_planned("planned.asr", "asr", "真实语音识别 Provider（未配置）", ["audio.transcribe"])
    registry.register_planned("planned.tts", "tts", "真实语音合成 Provider（未配置）", ["audio.synthesize"])
    registry.register_planned("planned.embedding", "embedding", "真实 Embedding Provider（未配置）", ["text.embed"])
    registry.register_planned(
        "planned.media_processor", "media_processor", "真实媒体检查 Provider（未配置）", ["media.inspect"]
    )
    registry.register_planned("planned.reranker", "reranker", "真实文本重排 Provider（未配置）", ["text.rerank"])
    registry.register_planned("planned.video", "video", "真实视频理解 Provider（未配置）", ["video.describe"])
    return registry
