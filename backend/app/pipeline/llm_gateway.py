"""模型网关：Provider 解析、预算硬阻断、超时、安全重试与显式测试。

显式测试（连通性 / 真实生成）只做单次尝试，不自动重试、不回退；
流水线调用仍保留按错误分类的有限重试与一次受控回退。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.adapters.llm.anthropic_native import DEFAULT_BASE_URL as ANTHROPIC_DEFAULT_BASE_URL
from app.adapters.llm.anthropic_native import AnthropicNativeProvider
from app.adapters.llm.base import BaseLLMProvider
from app.adapters.llm.http_utils import (
    RETRY_SAFETY_AMBIGUOUS,
    RETRY_SAFETY_NONE,
    RETRY_SAFETY_SAFE,
)
from app.adapters.llm.mock import MockLLMProvider
from app.adapters.llm.openai_compatible import OpenAICompatibleProvider
from app.budgets.service import BudgetService
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import CredentialCipher, redact_text
from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.models.group import Group
from app.models.provider import LLMProvider, LLMUsage
from app.pipeline.operations import ProviderOperationRegistry, validate_operation_id
from app.pipeline.provider_limiter import ProviderLimiter
from app.schemas.llm import (
    LLMRequest,
    LLMResponse,
    ModelListResult,
    ProviderTestRecord,
    ProviderTestResult,
    ProviderTestUsage,
)

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

TEST_KINDS = {"connectivity", "generation"}
CONNECTIVITY_PROMPT = "请只回复 OK"
GENERATION_PROMPT = "请用一句话介绍你自己。"
CONNECTIVITY_MAX_TOKENS = 8
CONNECTIVITY_TOKEN_CAP = 32
GENERATION_MAX_TOKENS = 32
GENERATION_TOKEN_CAP = 128

NEXT_STEPS = {
    ErrorCode.LLM_AUTH_FAILED: "检查 API Key 是否有效、是否已过期，以及是否被删除或替换。",
    ErrorCode.LLM_QUOTA_EXCEEDED: "检查服务商账户余额、额度与账单状态，处理后再测试。",
    ErrorCode.LLM_RATE_LIMITED: "稍后再试，或降低请求频率；不要通过并发重试绕过限流。",
    ErrorCode.LLM_TIMEOUT: "检查网络和超时设置；超时可能已产生费用，默认不会自动重试。",
    ErrorCode.LLM_NETWORK_ERROR: "检查 Base URL、网络与代理配置；确认服务状态后重试。",
    ErrorCode.LLM_MODEL_NOT_FOUND: "核对模型 ID 与 Base URL；必要时先获取模型列表。",
    ErrorCode.LLM_INVALID_RESPONSE: "检查 Base URL 是否指向兼容接口，或提示词/参数是否超出限制。",
    ErrorCode.LLM_NOT_CONFIGURED: "补全 Base URL、模型 ID 与 API Key 后再测试。",
    ErrorCode.BUDGET_EXCEEDED: "调整预算策略，或为 Provider 填写单价后再测试。",
    ErrorCode.LLM_CANCELLED: "已取消本地等待；服务商可能仍会生成并计费。",
}


class _OperationConflict(Exception):
    """operation_id 冲突是本地状态错误，不能记为模型调用失败。"""

    def __init__(self, error: AppError) -> None:
        super().__init__(error.message)
        self.error = error


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
    usage: ProviderTestUsage | None = None


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
        *,
        limiter: ProviderLimiter | None = None,
        operations: ProviderOperationRegistry | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.cipher = cipher
        self.budget_service = budget_service
        self.limiter = limiter or ProviderLimiter(
            max_concurrency=settings.llm_max_concurrency_per_provider,
            min_interval_ms=settings.llm_min_interval_ms,
        )
        self.operations = operations or ProviderOperationRegistry()
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

    def _build_adapter(self, record: LLMProvider, *, require_model: bool = True) -> BaseLLMProvider:
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
            if require_model and not record.model:
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
                    model=record.model or "",
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
                model=record.model or "",
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

    def _adapter_for(self, record: LLMProvider, *, require_model: bool = True) -> BaseLLMProvider:
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
        adapter = self._build_adapter(record, require_model=require_model)
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

    def _retry_after_seconds(self, error: AppError) -> float | None:
        value = error.details.get("retry_after_seconds")
        try:
            seconds = float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
        if seconds is None or seconds < 0:
            return None
        return seconds

    def _should_retry(self, error: AppError, *, attempt: int, retries: int) -> bool:
        if error.code == ErrorCode.LLM_CANCELLED or not error.retryable:
            return False
        if attempt >= retries:
            return False
        safety = str(error.details.get("retry_safety") or "")
        if not safety:
            safety = RETRY_SAFETY_AMBIGUOUS if error.code == ErrorCode.LLM_TIMEOUT else RETRY_SAFETY_SAFE
        if safety == RETRY_SAFETY_NONE:
            return False
        if safety == RETRY_SAFETY_AMBIGUOUS and not self.settings.llm_retry_ambiguous_timeouts:
            return False
        retry_after = self._retry_after_seconds(error)
        if retry_after is not None and retry_after > self.settings.llm_retry_after_max_seconds:
            return False
        return True

    def _retry_delay(self, error: AppError, *, attempt: int) -> float:
        retry_after = self._retry_after_seconds(error)
        if retry_after is not None:
            return min(retry_after, self.settings.llm_retry_after_max_seconds)
        base = min(
            self.settings.llm_retry_base_seconds * (2**attempt),
            self.settings.llm_retry_max_seconds,
        )
        jitter = random.uniform(0.0, max(0.0, self.settings.llm_retry_jitter_seconds))
        return base + jitter

    async def _call_provider(
        self,
        provider: _ResolvedProvider,
        request: LLMRequest,
        *,
        message_id: str | None,
        conversation_id: str | None,
        group_id: str | None,
        account_id: str | None,
        feature: str | None,
        retries: int | None = None,
        operation_id: str | None = None,
    ) -> LLMResult:
        await self.budget_service.assert_allowed(
            group_id=group_id,
            provider_id=provider.provider_id,
            account_id=account_id,
            feature=feature or request.purpose,
        )
        payload = request.model_copy(update={"model": provider.model})
        retry_limit = max(0, self.settings.llm_max_retries if retries is None else retries)
        attempts = 0
        started = time.perf_counter()
        last_error: AppError | None = None
        for attempt in range(retry_limit + 1):
            attempts = attempt + 1
            attempt_started = time.perf_counter()
            task: asyncio.Task[LLMResponse] | None = None
            try:
                async with self.limiter.slot(provider.provider_id, is_mock=provider.is_mock):
                    task = asyncio.create_task(provider.adapter.generate(payload))
                    if operation_id:
                        try:
                            self.operations.begin(provider.provider_id, operation_id, task)
                        except AppError as exc:
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                            raise _OperationConflict(exc) from exc
                    response = await asyncio.wait_for(
                        task,
                        timeout=payload.timeout_seconds or self.settings.llm_timeout_seconds,
                    )
            except _OperationConflict as conflict:
                raise conflict.error
            except TimeoutError:
                last_error = AppError(
                    ErrorCode.LLM_TIMEOUT,
                    "模型请求超时。",
                    status_code=504,
                    details={"retry_safety": RETRY_SAFETY_AMBIGUOUS},
                    retryable=True,
                )
            except asyncio.CancelledError:
                if operation_id is None:
                    raise
                last_error = AppError(
                    ErrorCode.LLM_CANCELLED,
                    "已取消本地等待；无法保证服务商停止生成或停止计费。",
                    status_code=499,
                    details={"retry_safety": RETRY_SAFETY_NONE},
                    retryable=False,
                )
            except AppError as exc:
                last_error = exc
            except Exception as exc:  # 防御性：适配器 bug 不应让流水线崩溃
                last_error = AppError(
                    ErrorCode.LLM_NETWORK_ERROR,
                    "模型调用发生未知错误。",
                    status_code=502,
                    details={
                        "reason": type(exc).__name__,
                        "retry_safety": RETRY_SAFETY_NONE,
                    },
                    retryable=False,
                )
            else:
                latency_ms = int((time.perf_counter() - attempt_started) * 1000)
                usage = await self._record_usage(
                    provider_id=provider.provider_id,
                    provider_type=provider.provider_type,
                    model=provider.model,
                    purpose=payload.purpose,
                    message_id=message_id,
                    conversation_id=conversation_id,
                    group_id=group_id,
                    account_id=account_id,
                    feature=feature,
                    response=response,
                    latency_ms=latency_ms,
                    status="success",
                    error_code=None,
                    request_id=response.request_id,
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
                    usage=usage,
                )
            finally:
                if operation_id and task is not None:
                    self.operations.finish(provider.provider_id, operation_id, task)

            latency_ms = int((time.perf_counter() - attempt_started) * 1000)
            cancelled = last_error.code == ErrorCode.LLM_CANCELLED
            await self._record_usage(
                provider_id=provider.provider_id,
                provider_type=provider.provider_type,
                model=provider.model,
                purpose=payload.purpose,
                message_id=message_id,
                conversation_id=conversation_id,
                group_id=group_id,
                account_id=account_id,
                feature=feature,
                response=None,
                latency_ms=latency_ms,
                status="cancelled" if cancelled else "error",
                error_code=last_error.code,
                request_id=str(last_error.details.get("upstream_request_id") or "") or None,
            )
            if not cancelled:
                await self._update_provider_health(
                    provider.provider_id,
                    healthy=False,
                    error=last_error.message,
                )
            if not self._should_retry(last_error, attempt=attempt, retries=retry_limit):
                break
            await asyncio.sleep(self._retry_delay(last_error, attempt=attempt))
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
        account_id: str | None = None,
        feature: str | None = None,
    ) -> LLMResult:
        if account_id is None and group_id:
            async with self.database.session() as session:
                group = await session.get(Group, group_id)
            account_id = group.account_id if group is not None else None
        route = await self._resolve_route(provider_id, group_id)
        primary = await self._resolve_primary(route)
        try:
            result = await self._call_provider(
                primary,
                request,
                message_id=message_id,
                conversation_id=conversation_id,
                group_id=group_id,
                account_id=account_id,
                feature=feature,
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
            if not primary.is_mock and fallback.is_mock:
                raise AppError(
                    ErrorCode.PROVIDER_FALLBACK_MOCK_FORBIDDEN,
                    "主模型调用失败，但备用模型是 Mock；为避免把模拟回复当成真实成功，已拒绝回退。",
                    status_code=409,
                    details={
                        **primary_error.details,
                        "primary_provider_id": primary.provider_id,
                        "primary_error_code": primary_error.code,
                        "fallback_provider_id": fallback.provider_id,
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
                    account_id=account_id,
                    feature=feature,
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
        account_id: str | None = None,
        feature: str | None = None,
        request_id: str | None = None,
    ) -> ProviderTestUsage | None:
        input_tokens = response.input_tokens if response else None
        output_tokens = response.output_tokens if response else None
        # 只有 Provider 明确返回了输入与输出 Token 时才估算费用；
        # 缺失用量时宁可标记为不可计价，也不能把未知成本记成 0。
        usage_complete = response is not None and input_tokens is not None and output_tokens is not None
        total = (input_tokens or 0) + (output_tokens or 0) if usage_complete else None
        cost = await self._estimate_cost(provider_id, input_tokens or 0, output_tokens or 0) if usage_complete else None
        summary: ProviderTestUsage | None = None
        if response is not None:
            if provider_type == "mock":
                cost_status = "mock_zero"
                note = "Mock 调用没有外部费用；结果为模拟，不代表真实模型可用。"
            elif usage_complete and cost is not None:
                cost_status = "estimated"
                note = "按本地填写的单价与 Token 估算，不是服务商账单。"
            else:
                cost_status = "unavailable"
                note = "缺少单价或 Token，无法估算费用；不会补成 0。"
            summary = ProviderTestUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total,
                estimated_cost=cost,
                cost_status=cost_status,
                note=note,
            )
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
                    account_id=account_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total,
                    latency_ms=latency_ms,
                    estimated_cost=cost,
                    status=status,
                    error_code=error_code,
                    request_id=request_id[:64] if request_id else None,
                )
            )
            await session.commit()
        await self.budget_service.record(
            provider_id=provider_id,
            group_id=group_id,
            account_id=account_id,
            feature=feature or purpose,
            requests=1,
            tokens=float(total or 0),
            estimated_cost=cost,
        )
        return summary

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
                # last_tested_at 只由显式测试更新，普通流水线调用不代表用户测试。
                await session.commit()
        except Exception:
            return

    async def _persist_test_record(
        self,
        provider_id: str,
        *,
        kind: str,
        result: ProviderTestRecord,
        update_health: bool,
    ) -> None:
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
            if record is None:
                return
            payload = result.model_dump(mode="json")
            if kind == "generation":
                record.last_generation_json = payload
            else:
                record.last_test_json = payload
            if update_health:
                record.status = "available" if result.ok else "error"
                record.last_error = None if result.ok else (result.message or result.error_code)
                record.last_tested_at = utcnow()
            await session.commit()

    def _next_step(self, error_code: str | None) -> str | None:
        if not error_code:
            return None
        return NEXT_STEPS.get(error_code)

    async def test_provider(
        self,
        provider_id: str,
        *,
        kind: str = "connectivity",
        prompt: str | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        operation_id: str | None = None,
    ) -> ProviderTestResult:
        if kind not in TEST_KINDS:
            raise AppError(ErrorCode.VALIDATION_ERROR, "测试类型必须为 connectivity 或 generation。", status_code=400)
        if operation_id:
            validate_operation_id(operation_id)
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
            if record is None:
                raise AppError(ErrorCode.PROVIDER_NOT_FOUND, "模型 Provider 不存在。", status_code=404)
            provider_type = record.provider_type
            provider_enabled = record.enabled
            model = record.model or ("mock-model" if provider_type == "mock" else "")
            is_mock = provider_type == "mock"
            record_temperature = record.temperature
            timeout_seconds = record.timeout_seconds

        if kind == "connectivity":
            effective_prompt = (prompt or "").strip() or CONNECTIVITY_PROMPT
            token_limit = CONNECTIVITY_MAX_TOKENS if max_output_tokens is None else int(max_output_tokens)
            token_limit = min(max(token_limit, 1), CONNECTIVITY_TOKEN_CAP)
            effective_temperature = 0.0
        else:
            effective_prompt = (prompt or "").strip() or GENERATION_PROMPT
            token_limit = GENERATION_MAX_TOKENS if max_output_tokens is None else int(max_output_tokens)
            token_limit = min(max(token_limit, 1), GENERATION_TOKEN_CAP)
            effective_temperature = min(
                max(float(temperature if temperature is not None else record_temperature), 0.0), 2.0
            )

        started = time.perf_counter()
        tested_at = iso_utc(utcnow()) or ""
        try:
            adapter = self._adapter_for(record)
        except AppError as exc:
            result = self._test_failure_result(
                provider_id=provider_id,
                provider_type=provider_type,
                provider_enabled=provider_enabled,
                model=model,
                is_mock=is_mock,
                kind=kind,
                tested_at=tested_at,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=exc,
                operation_id=operation_id,
            )
            await self._persist_test_record(
                provider_id,
                kind=kind,
                result=ProviderTestRecord.model_validate(result.model_dump()),
                update_health=True,
            )
            return result

        provider = _ResolvedProvider(
            provider_id=provider_id,
            provider_type=provider_type,
            model=adapter.model,
            adapter=adapter,
            is_mock=is_mock,
        )
        request = LLMRequest(
            model=adapter.model,
            messages=[{"role": "user", "content": effective_prompt}],
            temperature=effective_temperature,
            max_output_tokens=token_limit,
            timeout_seconds=timeout_seconds,
            purpose="test",
        )
        try:
            call = await self._call_provider(
                provider,
                request,
                message_id=None,
                conversation_id=None,
                group_id=None,
                account_id=None,
                feature="provider_test",
                retries=0,
                operation_id=operation_id,
            )
        except AppError as exc:
            # 预算阻断和本地操作冲突不是“测试结果”，必须保留 HTTP 状态码。
            if exc.code in (ErrorCode.BUDGET_EXCEEDED, ErrorCode.PROVIDER_OPERATION_CONFLICT):
                raise
            result = self._test_failure_result(
                provider_id=provider_id,
                provider_type=provider_type,
                provider_enabled=provider_enabled,
                model=model,
                is_mock=is_mock,
                kind=kind,
                tested_at=tested_at,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=exc,
                operation_id=operation_id,
            )
            await self._persist_test_record(
                provider_id,
                kind=kind,
                result=ProviderTestRecord.model_validate(result.model_dump()),
                update_health=exc.code != ErrorCode.LLM_CANCELLED,
            )
            return result

        preview = redact_text(call.response.text)[:160]
        text = redact_text(call.response.text)[:4000]
        if kind == "generation":
            message = "Mock 模拟生成成功；这不是真实模型输出。" if is_mock else "真实模型生成成功。"
        else:
            message = "Mock 模拟连接正常；这不代表真实 API 可用。" if is_mock else "模型连接成功。"
        result = ProviderTestResult(
            provider_id=provider_id,
            provider_type=provider_type,
            provider_enabled=provider_enabled,
            kind=kind,
            outcome="success",
            ok=True,
            tested_at=tested_at,
            latency_ms=call.latency_ms,
            attempts=call.attempts,
            model=call.model,
            is_mock=call.is_mock,
            billable=not call.is_mock,
            operation_id=operation_id,
            message=message,
            reply_preview=preview,
            text=text,
            upstream_request_id=call.response.request_id[:128] if call.response.request_id else None,
            usage=call.usage,
        )
        await self._persist_test_record(
            provider_id,
            kind=kind,
            result=ProviderTestRecord.model_validate(result.model_dump()),
            update_health=True,
        )
        return result

    def _test_failure_result(
        self,
        *,
        provider_id: str,
        provider_type: str,
        provider_enabled: bool,
        model: str,
        is_mock: bool,
        kind: str,
        tested_at: str,
        latency_ms: int,
        error: AppError,
        operation_id: str | None,
    ) -> ProviderTestResult:
        outcome = "cancelled" if error.code == ErrorCode.LLM_CANCELLED else "failure"
        retry_after = self._retry_after_seconds(error)
        attempt_count = int(error.details.get("attempts") or 1)
        return ProviderTestResult(
            provider_id=provider_id,
            provider_type=provider_type,
            provider_enabled=provider_enabled,
            kind=kind,
            outcome=outcome,
            ok=False,
            tested_at=tested_at,
            latency_ms=latency_ms,
            attempts=attempt_count,
            model=model,
            is_mock=is_mock,
            billable=not is_mock,
            operation_id=operation_id,
            message=redact_text(error.message)[:500],
            error_code=error.code,
            retryable=bool(error.retryable),
            retry_after_seconds=retry_after,
            next_step=self._next_step(error.code),
            upstream_request_id=(str(error.details.get("upstream_request_id") or "")[:128] or None),
        )

    async def list_models(self, provider_id: str) -> ModelListResult:
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
            if record is None:
                raise AppError(ErrorCode.PROVIDER_NOT_FOUND, "模型 Provider 不存在。", status_code=404)
            model = record.model
            is_mock = record.provider_type == "mock"
        try:
            adapter = self._adapter_for(record, require_model=False)
            async with self.limiter.slot(provider_id, is_mock=is_mock):
                result = await adapter.list_models(timeout_seconds=self.settings.llm_model_list_timeout_seconds)
        except AppError as exc:
            return ModelListResult(
                supported=False,
                state=self._model_list_state(exc.code),
                message=exc.message,
                error_code=exc.code,
                fetched_at=iso_utc(utcnow()),
                note="模型列表失败不代表生成一定失败；可手动填写模型 ID 后测试连通性。",
            )
        if result.models:
            listed = {item.id for item in result.models}
            result.current_model_listed = bool(model and model in listed) if model else None
        return result

    @staticmethod
    def _model_list_state(error_code: str) -> str:
        return {
            ErrorCode.LLM_NOT_CONFIGURED: "not_configured",
            ErrorCode.LLM_AUTH_FAILED: "auth_failed",
            ErrorCode.LLM_RATE_LIMITED: "rate_limited",
            ErrorCode.LLM_TIMEOUT: "timeout",
            ErrorCode.LLM_NETWORK_ERROR: "network_error",
            ErrorCode.LLM_INVALID_RESPONSE: "invalid_response",
            ErrorCode.LLM_MODEL_NOT_FOUND: "unsupported",
        }.get(error_code, "error")

    def cancel_operation(self, provider_id: str, operation_id: str) -> bool:
        return self.operations.cancel(provider_id, operation_id)

    async def evict(self, provider_id: str) -> None:
        cached = self._cache.pop(provider_id, None)
        if cached is not None:
            await cached[1].close()

    async def close(self) -> None:
        for _signature, adapter in self._cache.values():
            await adapter.close()
        self._cache.clear()
