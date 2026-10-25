"""LLM Provider 抽象。业务层只依赖该接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.schemas.llm import ConnectionTestResult, LLMRequest, LLMResponse


class BaseLLMProvider(ABC):
    provider_type: str = "base"
    is_mock: bool = False

    def __init__(
        self,
        *,
        provider_id: str,
        name: str,
        model: str | None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 45.0,
        max_output_tokens: int = 800,
        temperature: float = 0.7,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.name = name
        self.model = model or ""
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.config = config or {}

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(self) -> ConnectionTestResult:
        raise NotImplementedError

    async def close(self) -> None:
        return None

    def info(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "name": self.name,
            "provider_type": self.provider_type,
            "model": self.model,
            "base_url": self.base_url,
            "is_mock": self.is_mock,
        }
