"""按能力、状态与优先级选择多模态 Provider，并记录选择结果。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.adapters.media.base import BaseMediaProvider
from app.core.errors import AppError, ErrorCode
from app.providers.registry import CAPABILITY_TYPES, ProviderRegistry


@dataclass
class RouteDecision:
    capability: str
    selected_provider_id: str | None
    candidates: list[str] = field(default_factory=list)
    fallback_reason: str | None = None
    planned: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability,
            "selected_provider_id": self.selected_provider_id,
            "candidates": self.candidates,
            "fallback_reason": self.fallback_reason,
            "planned": self.planned,
        }


class CapabilityRouter:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry

    def candidates(self, capability: str) -> list[BaseMediaProvider]:
        return self.registry.available_for(capability)

    def select(self, capability: str) -> tuple[BaseMediaProvider, RouteDecision]:
        if capability not in CAPABILITY_TYPES:
            raise AppError(ErrorCode.PROVIDER_CAPABILITY_MISSING, "未知的媒体能力。", status_code=400)
        providers = self.candidates(capability)
        if not providers:
            entries = self.registry.list_entries(CAPABILITY_TYPES[capability])
            # 只有全部已注册实现都是规划占位时才是 planned；仅仅“已停用”是实现存在但未启用。
            planned = bool(entries) and all(entry.planned for entry in entries)
            raise AppError(
                ErrorCode.PROVIDER_CAPABILITY_MISSING,
                "该媒体能力当前未配置可用 Provider。请先在「能力中心」启用 Mock Provider，或配置真实 Provider。",
                status_code=503,
                details={
                    "capability": capability,
                    "planned": planned,
                    "state": "planned" if planned else "unconfigured",
                },
            )
        provider = providers[0]
        decision = RouteDecision(
            capability=capability,
            selected_provider_id=provider.provider_id,
            candidates=[item.provider_id for item in providers],
        )
        return provider, decision
