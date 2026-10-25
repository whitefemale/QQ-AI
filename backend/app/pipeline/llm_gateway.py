"""模型网关：Provider 解析、预算硬阻断、超时、分类有限重试与用量记录。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.adapters.llm.anthropic_native import DEFAULT_BASE_URL as ANTHROPIC_DEFAULT_BASE_URL
from app.adapters.llm.anthropic_native import AnthropicNativeProvider
from app.adapters.llm.base import BaseLLMProvider
from app.adapters.llm.mock import MockLLMProvider
from app.adapters.llm.openai_compatible import OpenAICompatibleProvider
from app.budgets.service import BudgetService
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import CredentialCipher
from app.core.time import utcnow
from app.db.session import Database
from app.models.group import Group
from app.models.provider import LLMProvider, LLMUsage
from app.schemas.llm import ConnectionTestResult, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

# 只有 Provider 自身的调用失败才允许切换备用模型。
# 配置、预算、暂停和凭证错误必须直接暴露，不能借回退绕过。
FALLBACK_ERROR_CODES = {
    ErrorCode.LLM_TIMEOUT,
    ErrorCode.LLM_NETWORK_ERROR,
    ErrorCode.LLM_AUTH_FAILED,
    ErrorCode.LLM_RATE_LIMITED,
    ErrorCode.LLM_QUOTA_EXCEEDED,
    ErrorCode.LLM_MODEL_NOT_FOUND,
    ErrorCode.LLM_INVALID_RESPONSE,
    ErrorCode.PROVIDER_UNHEALTHY,
}


@dataclass
class LLMResult:
    response: LLMResponse
    provider_id: str
    provider_type: str
    model: str
    latency_ms: int
    attempts: int
    is_mock: bool
    fallback_used: bool = False
    primary_provider_id: str | None = None
    primary_error_code: str | None = None
    primary_attempts: int = 0
    route_source: str = "default"


@dataclass
class _Route:
    primary_id: str | None
    fallback_id: str | None
    source: str


@dataclass
class _ResolvedProvider:
    provider_id: str
    provider_type: str
    model: str
    adapter: BaseLLMProvider
    is_mock: bool


class LLMGateway:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        cipher: CredentialCipher,
        budget_service: BudgetService,
    ) -> None:
        self.database = database
        self.settings = settings
        self.cipher = cipher
        self.budget_service = budget_service
        self._cache: dict[str, tuple[str, BaseLLMProvider]] = {}

    async def _provider_record(self, provider_id: str | None) -> LLMProvider | None:
        async with self.database.session() as session:
            if provider_id:
                record = await session.get(LLMProvider, provider_id)
                return record if record is not None and record.enabled else None
            return await session.scalar(
                select(LLMProvider)
                .where(LLMProvider.enabled.is_(True))
                .order_by(LLMProvider.is_default.desc(), LLMProvider.created_at)
                .limit(1)
            )

    def _build_adapter(self, record: LLMProvider) -> BaseLLMProvider:
        config = dict(record.config_json or {})
        if record.provider_type == "mock":
            return MockLLMProvider(
                provider_id=record.id,
                name=record.name,
                model=record.model or "mock-model",
                timeout_seconds=record.timeout_seconds,
                max_output_tokens=record.max_output_tokens,
                temperature=record.temperature,
                config=config,
            )
        if record.provider_type in {"openai_compatible", "anthropic_native"}:
            if not record.model:
                raise AppError(
                    ErrorCode.LLM_NOT_CONFIGURED,
                    "该模型 Provider 尚未配置模型 ID。",
                    status_code=400,
                )
            if record.provider_type == "openai_compatible" and not record.base_url:
                raise AppError(
                    ErrorCode.LLM_NOT_CONFIGURED,
                    "该模型 Provider 尚未配置 Base URL。",
                    status_code=400,
                )
            if not record.api_key_encrypted:
                raise AppError(
                    ErrorCode.LLM_NOT_CONFIGURED,
                    "该模型 Provider 尚未配置 API Key。",
                    status_code=400,
                )
            api_key = self.cipher.decrypt(record.api_key_encrypted)
            if record.provider_type == "anthropic_native":
                return AnthropicNativeProvider(
                    provider_id=record.id,
                    name=record.name,
                    model=record.model,
                    base_url=record.base_url or ANTHROPIC_DEFAULT_BASE_URL,
                    api_key=api_key,
                    timeout_seconds=record.timeout_seconds,
                    max_output_tokens=record.max_output_tokens,
                    temperature=record.temperature,
                    config=config,
                )
            return OpenAICompatibleProvider(
                provider_id=record.id,
                name=record.name,
                model=record.model,
                base_url=record.base_url,
                api_key=api_key,
                timeout_seconds=record.timeout_seconds,
                max_output_tokens=record.max_output_tokens,
                temperature=record.temperature,
                config=config,
            )
        raise AppError(
            ErrorCode.PROVIDER_PLANNED,
            f"模型 Provider 类型「{record.provider_type}」尚未实现。",
            status_code=501,
        )

    def _adapter_for(self, record: LLMProvider) -> BaseLLMProvider:
        signature = "|".join(
            [
                record.provider_type,
                record.base_url or "",
                record.model or "",
                record.api_key_encrypted or "",
                str(record.config_json),
            ]
        )
        cached = self._cache.get(record.id)
        if cached is not None and cached[0] == signature:
            return cached[1]
        adapter = self._build_adapter(record)
        self._cache[record.id] = (signature, adapter)
        return adapter

    async def _resolve_route(self, provider_id: str | None, group_id: str | None) -> _Route:
        # 显式 Provider 仅用于内部测试/特殊调用，优先于群绑定。
        if provider_id:
            return _Route(primary_id=provider_id, fallback_id=None, source="explicit")
        if group_id:
            async with self.database.session() as session:
                group = await session.get(Group, group_id)
            if group is not None and group.llm_provider_id:
                fallback_id = group.llm_fallback_provider_id
                if fallback_id == group.llm_provider_id:
                    fallback_id = None
                return _Route(
                    primary_id=group.llm_provider_id,
                    fallback_id=fallback_id,
                    source="group_binding",
                )
        return _Route(primary_id=None, fallback_id=None, source="default")

    async def _resolve_named(self, provider_id: str, *, role: str) -> _ResolvedProvider:
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
        if record is None:
            raise AppError(
                ErrorCode.PROVIDER_NOT_FOUND,
                f"{role}模型 Provider 不存在，请检查群级模型配置。",
                status_code=503,
                details={"provider_id": provider_id, "role": role},
            )
        if not record.enabled:
            raise AppError(
                ErrorCode.PROVIDER_DISABLED,
                f"{role}模型 Provider 已禁用，请先在「模型 API」中启用。",
                status_code=503,
                details={"provider_id": provider_id, "role": role},
            )
        adapter = self._adapter_for(record)
        return _ResolvedProvider(
            provider_id=record.id,
            provider_type=record.provider_type,
            model=adapter.model,
            adapter=adapter,
            is_mock=record.provider_type == "mock",
        )

    async def _resolve_default(self) -> _ResolvedProvider:
        record = await self._provider_record(None)
        if record is not None:
            adapter = self._adapter_for(record)
            return _ResolvedProvider(
                provider_id=record.id,
                provider_type=record.provider_type,
                model=adapter.model,
                adapter=adapter,
                is_mock=record.provider_type == "mock",
            )
        if self.settings.default_llm_base_url and self.settings.default_llm_model:
            if not self.settings.default_llm_api_key:
                raise AppError(
                    ErrorCode.LLM_NOT_CONFIGURED,
                    "尚未配置可用模型。请在控制台添加 Provider，或在 .env 配置默认模型。",
                    status_code=503,
                )
            adapter = OpenAICompatibleProvider(
                provider_id="env-default",
                name="环境变量默认模型",
                model=self.settings.default_llm_model,
                base_url=self.settings.default_llm_base_url,
                api_key=self.settings.default_llm_api_key,
                timeout_seconds=self.settings.llm_timeout_seconds,
                max_output_tokens=800,
            )
            return _ResolvedProvider(
                provider_id="env-default",
                provider_type="openai_compatible",
                model=adapter.model,
                adapter=adapter,
                is_mock=False,
            )
        raise AppError(
            ErrorCode.LLM_NOT_CONFIGURED,
            "尚未配置可用模型。请先在「模型 API」中创建并启用一个 Provider。",
            status_code=503,
        )

    async def _resolve_primary(self, route: _Route) -> _ResolvedProvider:
        if route.primary_id:
            return await self._resolve_named(route.primary_id, role="主")
        return await self._resolve_default()

    async def _call_provider(
        self,
        provider: _ResolvedProvider,
        request: LLMRequest,
        *,
        message_id: str | None,
        conversation_id: str | None,
        group_id: str | None,
    ) -> LLMResult:
        await self.budget_service.assert_allowed(group_id=group_id, provider_id=provider.provider_id)
        payload = request.model_copy(update={"model": provider.model})
        retries = max(0, self.settings.llm_max_retries)
        attempts = 0
        started = time.perf_counter()
        last_error: AppError | None = None
        for attempt in range(retries + 1):
            attempts = attempt + 1
            attempt_started = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    provider.adapter.generate(payload),
                    timeout=payload.timeout_seconds or self.settings.llm_timeout_seconds,
                )
            except TimeoutError:
                last_error = AppError(ErrorCode.LLM_TIMEOUT, "模型请求超时。", status_code=504, retryable=True)
            except AppError as exc:
                last_error = exc
            except Exception as exc:  # 防御性：适配器 bug 不应让流水线崩溃
                last_error = AppError(
                    ErrorCode.LLM_NETWORK_ERROR,
                    "模型调用发生未知错误。",
                    status_code=502,
                    details={"reason": type(exc).__name__},
                    retryable=False,
                )
            else:
                latency_ms = int((time.perf_counter() - attempt_started) * 1000)
                await self._record_usage(
                    provider_id=provider.provider_id,
                    provider_type=provider.provider_type,
                    model=provider.model,
                    purpose=payload.purpose,
                    message_id=message_id,
                    conversation_id=conversation_id,
                    group_id=group_id,
                    response=response,
                    latency_ms=latency_ms,
                    status="success",
                    error_code=None,
                )
                await self._update_provider_health(provider.provider_id, healthy=True, error=None)
                return LLMResult(
                    response=response,
                    provider_id=provider.provider_id,
                    provider_type=provider.provider_type,
                    model=provider.model,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    attempts=attempts,
                    is_mock=provider.is_mock,
                )

            latency_ms = int((time.perf_counter() - attempt_started) * 1000)
            await self._record_usage(
                provider_id=provider.provider_id,
                provider_type=provider.provider_type,
                model=provider.model,
                purpose=payload.purpose,
                message_id=message_id,
                conversation_id=conversation_id,
                group_id=group_id,
                response=None,
                latency_ms=latency_ms,
                status="error",
                error_code=last_error.code if last_error else ErrorCode.INTERNAL_ERROR,
            )
            await self._update_provider_health(
                provider.provider_id,
                healthy=False,
                error=last_error.message if last_error else "模型调用失败。",
            )
            if not last_error or not last_error.retryable or attempt >= retries:
                break
            await asyncio.sleep(min(0.3 * (2**attempt), 1.5))
        assert last_error is not None
        last_error.details = {
            **last_error.details,
            "provider_id": provider.provider_id,
            "attempts": attempts,
        }
        raise last_error

    async def generate(
        self,
        request: LLMRequest,
        *,
        provider_id: str | None = None,
        message_id: str | None = None,
        conversation_id: str | None = None,
        group_id: str | None = None,
    ) -> LLMResult:
        route = await self._resolve_route(provider_id, group_id)
        primary = await self._resolve_primary(route)
        try:
            result = await self._call_provider(
                primary,
                request,
                message_id=message_id,
                conversation_id=conversation_id,
                group_id=group_id,
            )
        except AppError as primary_error:
            if not route.fallback_id or primary_error.code not in FALLBACK_ERROR_CODES:
                raise
            try:
                fallback = await self._resolve_named(route.fallback_id, role="备用")
            except AppError as fallback_config_error:
                raise AppError(
                    primary_error.code,
                    f"主模型调用失败（{primary_error.message}），备用模型不可用：{fallback_config_error.message}",
                    status_code=primary_error.status_code,
                    details={
                        **primary_error.details,
                        "fallback_provider_id": route.fallback_id,
                        "fallback_error_code": fallback_config_error.code,
                    },
                    retryable=False,
                ) from primary_error
            try:
                result = await self._call_provider(
                    fallback,
                    request,
                    message_id=message_id,
                    conversation_id=conversation_id,
                    group_id=group_id,
                )
            except AppError as fallback_error:
                raise AppError(
                    fallback_error.code,
                    f"主模型失败，备用模型也失败：{fallback_error.message}",
                    status_code=fallback_error.status_code,
                    details={
                        **fallback_error.details,
                        "provider_id": fallback.provider_id,
                        "primary_provider_id": primary.provider_id,
                        "primary_error_code": primary_error.code,
                        "fallback_error_code": fallback_error.code,
                    },
                    retryable=False,
                ) from fallback_error
            logger.warning(
                "llm fallback used",
                extra={
                    "event": "llm.fallback",
                    "group_id": group_id,
                    "primary_provider_id": primary.provider_id,
                    "fallback_provider_id": fallback.provider_id,
                    "primary_error_code": primary_error.code,
                },
            )
            result.fallback_used = True
            result.primary_provider_id = primary.provider_id
            result.primary_error_code = primary_error.code
            result.primary_attempts = int(primary_error.details.get("attempts") or 0)
            result.route_source = route.source
            return result
        result.primary_provider_id = primary.provider_id
        result.primary_attempts = result.attempts
        result.route_source = route.source
        return result

    async def _record_usage(
        self,
        *,
        provider_id: str,
        provider_type: str,
        model: str,
        purpose: str,
        message_id: str | None,
        conversation_id: str | None,
        group_id: str | None,
        response: LLMResponse | None,
        latency_ms: int,
        status: str,
        error_code: str | None,
    ) -> None:
        input_tokens = response.input_tokens if response else None
        output_tokens = response.output_tokens if response else None
        # 只有 Provider 明确返回了输入与输出 Token 时才估算费用；
        # 缺失用量时宁可标记为不可计价，也不能把未知成本记成 0。
        usage_complete = response is not None and input_tokens is not None and output_tokens is not None
        total = (input_tokens or 0) + (output_tokens or 0) if usage_complete else None
        cost = await self._estimate_cost(provider_id, input_tokens or 0, output_tokens or 0) if usage_complete else None
        async with self.database.session() as session:
            session.add(
                LLMUsage(
                    provider_id=provider_id,
                    provider_type=provider_type,
                    model=model,
                    purpose=purpose,
                    message_id=message_id,
                    conversation_id=conversation_id,
                    group_id=group_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total,
                    latency_ms=latency_ms,
                    estimated_cost=cost,
                    status=status,
                    error_code=error_code,
                )
            )
            await session.commit()
        await self.budget_service.record(
            provider_id=provider_id,
            group_id=group_id,
            feature=purpose,
            requests=1,
            tokens=float(total or 0),
            estimated_cost=cost,
        )

    async def _estimate_cost(self, provider_id: str, input_tokens: int, output_tokens: int) -> float | None:
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
        if record is None:
            return None
        # Mock 没有外部计费；即使 config 中误填了单价，也不能生成虚构费用。
        if record.provider_type == "mock":
            return None
        config = record.config_json or {}
        try:
            input_price = float(config.get("input_price_per_1k", 0) or 0)
            output_price = float(config.get("output_price_per_1k", 0) or 0)
        except (TypeError, ValueError):
            return None
        if input_price <= 0 and output_price <= 0:
            return None
        return round(input_tokens / 1000 * input_price + output_tokens / 1000 * output_price, 8)

    async def _update_provider_health(self, provider_id: str, *, healthy: bool, error: str | None) -> None:
        if provider_id == "env-default":
            return
        try:
            async with self.database.session() as session:
                record = await session.get(LLMProvider, provider_id)
                if record is None:
                    return
                record.status = "available" if healthy else "error"
                record.last_error = error
                record.last_tested_at = utcnow()
                await session.commit()
        except Exception:
            return

    async def test_provider(self, provider_id: str) -> ConnectionTestResult:
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
        if record is None:
            raise AppError(ErrorCode.PROVIDER_NOT_FOUND, "模型 Provider 不存在。", status_code=404)
        try:
            adapter = self._adapter_for(record)
            result = await adapter.test_connection()
        except AppError as exc:
            result = ConnectionTestResult(ok=False, message=exc.message, error_code=exc.code)
        await self._update_provider_health(provider_id, healthy=result.ok, error=None if result.ok else result.message)
        if not result.ok:
            async with self.database.session() as session:
                current = await session.get(LLMProvider, provider_id)
                if current is not None:
                    current.status = "error"
                    current.last_error = result.message
                    current.last_tested_at = utcnow()
                    await session.commit()
        return result

    async def evict(self, provider_id: str) -> None:
        cached = self._cache.pop(provider_id, None)
        if cached is not None:
            await cached[1].close()

    async def close(self) -> None:
        for _signature, adapter in self._cache.values():
            await adapter.close()
        self._cache.clear()


def response_preview(response: LLMResponse, limit: int = 120) -> str:
    return response.text[:limit]
