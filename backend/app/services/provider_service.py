"""模型 Provider 与媒体能力管理。所有密钥只返回掩码。"""

from __future__ import annotations

import ipaddress
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import or_, select

from app.adapters.llm.anthropic_native import DEFAULT_BASE_URL as DEFAULT_ANTHROPIC_BASE_URL
from app.budgets.service import provider_pricing_state
from app.core.errors import AppError, ErrorCode
from app.core.security import CredentialCipher, redact_value
from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.models.group import Group
from app.models.provider import LLMProvider
from app.models.provider import ProviderRegistry as MediaProviderState
from app.pipeline.llm_gateway import LLMGateway
from app.providers.registry import CAPABILITY_TYPES, ProviderRegistry
from app.schemas.llm import ProviderTestRecord
from app.services.audit import write_audit

if TYPE_CHECKING:
    from app.media.jobs import MediaJobService

logger = logging.getLogger(__name__)

# 当前任务队列真正支持执行的能力；其余能力只有契约与 Mock，不能假装已接入。
JOB_EXECUTABLE_CAPABILITIES = frozenset({"image.describe", "ocr.extract", "audio.transcribe", "text.embed"})

SUPPORTED_LLM_TYPES = {"mock", "openai_compatible", "anthropic_native"}
REMOTE_LLM_TYPES = {"openai_compatible", "anthropic_native"}

# 云元数据服务：只拒绝已知地址，不解析 DNS；本机与内网自建模型仍可配置。
_METADATA_HOSTS = {
    "169.254.169.254",
    "100.100.100.200",
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "metadata.tencentyun.com",
}
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("100.64.0.0/10"),
)


def _is_blocked_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address.is_link_local or address.is_multicast or address.is_unspecified:
        return True
    return any(address.version == network.version and address in network for network in _BLOCKED_NETWORKS)


def _clean(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    # 去除控制字符，避免换行/空字节进入日志、URL 或模型 ID。
    return "".join(ch for ch in text if ch >= " " and ch != "\x7f")[:limit]


def _clean_secret(value: Any, limit: int = 4096) -> str:
    text = str(value or "").strip()
    if any(ch < " " or ch == "\x7f" for ch in text):
        raise AppError(ErrorCode.VALIDATION_ERROR, "API Key 不能包含控制字符。", status_code=400)
    return text[:limit]


def normalize_base_url(value: Any, provider_type: str) -> str | None:
    """校验并归一化 Base URL；拒绝 userinfo、query、fragment 与已知完整端点后缀。"""
    raw = _clean(value, 512)
    if not raw:
        return None
    if any(ch.isspace() for ch in raw):
        raise AppError(ErrorCode.VALIDATION_ERROR, "Base URL 不能包含空白字符。", status_code=400)
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Base URL 必须为有效的 http:// 或 https:// 地址。",
            status_code=400,
        )
    if parsed.username is not None or parsed.password is not None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Base URL 不能包含用户名或密码。", status_code=400)
    if parsed.query or parsed.fragment:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Base URL 不能包含查询参数或片段。", status_code=400)
    host = (parsed.hostname or "").strip().strip("[]").rstrip(".").lower()
    if host in _METADATA_HOSTS or _is_blocked_ip(host):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Base URL 指向不允许的主机；请使用本机、内网或公网可用的模型服务地址。",
            status_code=400,
        )
    path = parsed.path.rstrip("/")
    if provider_type == "openai_compatible" and path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")]
    if provider_type == "anthropic_native":
        if path.endswith("/v1/messages"):
            path = path[: -len("/messages")]
        elif path.endswith("/messages"):
            path = path[: -len("/messages")]
    normalized = urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))
    if not normalized or len(normalized) > 512:
        raise AppError(ErrorCode.VALIDATION_ERROR, "Base URL 无效或过长。", status_code=400)
    return normalized


def _safe_test_record(value: Any) -> dict[str, Any] | None:
    """按 ProviderTestRecord 白名单读取历史证据，绝不透传任意 JSON。"""
    if not isinstance(value, dict):
        return None
    try:
        return ProviderTestRecord.model_validate(value).model_dump(mode="json")
    except Exception:
        return None


def _number(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, minimum), maximum)


class ProviderService:
    def __init__(
        self,
        database: Database,
        cipher: CredentialCipher,
        gateway: LLMGateway,
        registry: ProviderRegistry,
        media_jobs: MediaJobService | None = None,
    ) -> None:
        self.database = database
        self.cipher = cipher
        self.gateway = gateway
        self.registry = registry
        # 仅用于停用扩展时即时取消任务；测试/脚本可不注入。
        self.media_jobs = media_jobs

    # ------------------------------------------------------------------ LLM
    def _config_complete(self, record: LLMProvider) -> bool:
        if record.provider_type == "mock":
            return True
        if not record.model or not record.api_key_encrypted:
            return False
        if record.provider_type == "openai_compatible" and not record.base_url:
            return False
        return record.provider_type in REMOTE_LLM_TYPES

    def _llm_public(self, record: LLMProvider) -> dict[str, Any]:
        cost_tracking = provider_pricing_state(record)
        return {
            "id": record.id,
            "name": record.name,
            "provider_type": record.provider_type,
            "base_url": record.base_url,
            "model": record.model,
            "api_key_configured": bool(record.api_key_encrypted),
            "api_key_masked": self.cipher.mask_encrypted(record.api_key_encrypted),
            "timeout_seconds": record.timeout_seconds,
            "max_output_tokens": record.max_output_tokens,
            "temperature": record.temperature,
            "is_default": record.is_default,
            "enabled": record.enabled,
            "status": record.status,
            "config_complete": self._config_complete(record),
            "config": redact_value(dict(record.config_json or {})),
            "last_error": record.last_error,
            "last_tested_at": iso_utc(record.last_tested_at),
            "last_test": _safe_test_record(record.last_test_json),
            "last_generation": _safe_test_record(record.last_generation_json),
            "is_mock": record.provider_type == "mock",
            "cost_tracking": cost_tracking,
            "cost_pricing_configured": cost_tracking != "unconfigured",
            "created_at": iso_utc(record.created_at),
            "updated_at": iso_utc(record.updated_at),
        }

    async def list_llm_providers(self) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            records = list(
                (
                    await session.execute(
                        select(LLMProvider).order_by(LLMProvider.is_default.desc(), LLMProvider.created_at)
                    )
                ).scalars()
            )
            return [self._llm_public(record) for record in records]

    async def get_llm_provider(self, provider_id: str) -> dict[str, Any]:
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
            if record is None:
                raise AppError(ErrorCode.PROVIDER_NOT_FOUND, "模型 Provider 不存在。", status_code=404)
            return self._llm_public(record)

    def _validate_llm_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider_type = str(payload.get("provider_type") or "mock").strip()
        if provider_type in {"openai", "claude", "anthropic", "official"}:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "模型 Provider 类型无效；Anthropic 原生接入请选择 anthropic_native。",
                status_code=400,
            )
        if provider_type not in SUPPORTED_LLM_TYPES:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "模型 Provider 类型必须为 mock、openai_compatible 或 anthropic_native。",
                status_code=400,
            )
        base_url: str | None = None
        model = _clean(payload.get("model"), 128)
        if provider_type in REMOTE_LLM_TYPES:
            raw_base = _clean(payload.get("base_url"), 512)
            if provider_type == "anthropic_native" and not raw_base:
                raw_base = DEFAULT_ANTHROPIC_BASE_URL
            if not raw_base:
                raise AppError(ErrorCode.VALIDATION_ERROR, "请填写 Base URL。", status_code=400)
            base_url = normalize_base_url(raw_base, provider_type)
            if not model:
                raise AppError(ErrorCode.VALIDATION_ERROR, "请填写模型 ID。", status_code=400)
        return {
            "provider_type": provider_type,
            "base_url": base_url,
            "model": model or ("mock-model" if provider_type == "mock" else None),
        }

    async def create_llm_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _clean(payload.get("name"), 128)
        if not name:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Provider 名称不能为空。", status_code=400)
        fields = self._validate_llm_fields(payload)
        token = payload.get("api_key")
        if token is not None and not isinstance(token, str):
            raise AppError(ErrorCode.VALIDATION_ERROR, "API Key 必须为字符串。", status_code=400)
        api_key = _clean_secret(token) if isinstance(token, str) else ""
        if fields["provider_type"] in REMOTE_LLM_TYPES and not api_key:
            raise AppError(ErrorCode.VALIDATION_ERROR, "请填写 API Key。", status_code=400)
        raw_config: Any = payload.get("config")
        config: dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
        async with self.database.session() as session:
            has_enabled = await session.scalar(select(LLMProvider.id).where(LLMProvider.enabled.is_(True)).limit(1))
            record = LLMProvider(
                name=name,
                provider_type=fields["provider_type"],
                base_url=fields["base_url"],
                model=fields["model"],
                api_key_encrypted=self.cipher.encrypt(api_key) if api_key else None,
                timeout_seconds=_number(payload.get("timeout_seconds"), 45.0, 1.0, 300.0),
                max_output_tokens=int(_number(payload.get("max_output_tokens"), 800, 1, 32000)),
                temperature=_number(payload.get("temperature"), 0.7, 0.0, 2.0),
                is_default=bool(payload.get("is_default", not has_enabled)),
                enabled=bool(payload.get("enabled", True)),
                status="available" if fields["provider_type"] == "mock" else "configured",
                config_json={
                    "input_price_per_1k": _number(config.get("input_price_per_1k"), 0, 0, 1e6),
                    "output_price_per_1k": _number(config.get("output_price_per_1k"), 0, 0, 1e6),
                },
            )
            if record.is_default:
                for other in (
                    await session.execute(select(LLMProvider).where(LLMProvider.is_default.is_(True)))
                ).scalars():
                    other.is_default = False
            session.add(record)
            await session.commit()
            await session.refresh(record)
            public = self._llm_public(record)
            provider_id = record.id
        await write_audit(
            self.database,
            action="provider.llm.create",
            target_type="llm_provider",
            target_id=provider_id,
            details={"name": name, "provider_type": fields["provider_type"]},
        )
        return public

    async def update_llm_provider(self, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
            if record is None:
                raise AppError(ErrorCode.PROVIDER_NOT_FOUND, "模型 Provider 不存在。", status_code=404)
            # 配置敏感的字段一旦真实变化，旧测试证据即失效，必须重新测试。
            evidence_reset = False
            merged = {
                "provider_type": record.provider_type,
                "base_url": record.base_url,
                "model": record.model,
                **payload,
            }
            if any(key in payload for key in ("provider_type", "base_url", "model")):
                fields = self._validate_llm_fields(merged)
                if (
                    fields["provider_type"] != record.provider_type
                    or fields["base_url"] != record.base_url
                    or fields["model"] != record.model
                ):
                    evidence_reset = True
                record.provider_type = fields["provider_type"]
                record.base_url = fields["base_url"]
                record.model = fields["model"]
            if "name" in payload:
                name = _clean(payload.get("name"), 128)
                if not name:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "Provider 名称不能为空。", status_code=400)
                record.name = name
            if "api_key" in payload:
                token = payload.get("api_key")
                if not isinstance(token, str):
                    raise AppError(
                        ErrorCode.VALIDATION_ERROR,
                        "API Key 必须为字符串；如需清除已保存的 Key，请显式传空字符串。",
                        status_code=400,
                    )
                candidate = _clean_secret(token)
                current: str | None = None
                if record.api_key_encrypted:
                    try:
                        current = self.cipher.decrypt(record.api_key_encrypted)
                    except AppError:
                        current = None
                if candidate != (current or ""):
                    record.api_key_encrypted = self.cipher.encrypt(candidate) if candidate else None
                    evidence_reset = True
            if "timeout_seconds" in payload:
                value = _number(payload.get("timeout_seconds"), record.timeout_seconds, 1.0, 300.0)
                evidence_reset = evidence_reset or value != record.timeout_seconds
                record.timeout_seconds = value
            if "max_output_tokens" in payload:
                value = int(_number(payload.get("max_output_tokens"), record.max_output_tokens, 1, 32000))
                evidence_reset = evidence_reset or value != record.max_output_tokens
                record.max_output_tokens = value
            if "temperature" in payload:
                value = _number(payload.get("temperature"), record.temperature, 0.0, 2.0)
                evidence_reset = evidence_reset or value != record.temperature
                record.temperature = value
            if "enabled" in payload:
                record.enabled = bool(payload.get("enabled"))
            if isinstance(payload.get("config"), dict):
                config = payload["config"]
                record.config_json = {
                    "input_price_per_1k": _number(config.get("input_price_per_1k"), 0, 0, 1e6),
                    "output_price_per_1k": _number(config.get("output_price_per_1k"), 0, 0, 1e6),
                }
            if bool(payload.get("is_default")):
                for other in (
                    await session.execute(
                        select(LLMProvider).where(LLMProvider.id != provider_id, LLMProvider.is_default.is_(True))
                    )
                ).scalars():
                    other.is_default = False
                record.is_default = True
            elif "is_default" in payload:
                record.is_default = False
            if evidence_reset:
                record.last_test_json = None
                record.last_generation_json = None
                record.last_error = None
                record.last_tested_at = None
                if record.provider_type == "mock":
                    record.status = "available"
                elif self._config_complete(record):
                    record.status = "configured"
                else:
                    record.status = "unconfigured"
            await session.commit()
            await session.refresh(record)
            public = self._llm_public(record)
        await self.gateway.evict(provider_id)
        await write_audit(
            self.database,
            action="provider.llm.update",
            target_type="llm_provider",
            target_id=provider_id,
            details={"changed_fields": sorted(payload.keys())},
        )
        return public

    async def delete_llm_provider(self, provider_id: str) -> None:
        async with self.database.session() as session:
            record = await session.get(LLMProvider, provider_id)
            if record is None:
                raise AppError(ErrorCode.PROVIDER_NOT_FOUND, "模型 Provider 不存在。", status_code=404)
            groups = list(
                (
                    await session.execute(
                        select(Group).where(
                            or_(
                                Group.llm_provider_id == provider_id,
                                Group.llm_fallback_provider_id == provider_id,
                            )
                        )
                    )
                ).scalars()
            )
            if groups:
                raise AppError(
                    ErrorCode.PROVIDER_IN_USE,
                    f"该模型 Provider 仍被 {len(groups)} 个群绑定，请先在「群聊管理」中解除绑定。",
                    status_code=409,
                    details={"group_ids": [group.id for group in groups[:20]]},
                )
            name = record.name
            await session.delete(record)
            await session.commit()
        await self.gateway.evict(provider_id)
        await write_audit(
            self.database,
            action="provider.llm.delete",
            target_type="llm_provider",
            target_id=provider_id,
            details={"name": name},
        )

    async def list_provider_models(self, provider_id: str) -> dict[str, Any]:
        return (await self.gateway.list_models(provider_id)).model_dump(mode="json")

    async def test_llm_provider(
        self,
        provider_id: str,
        *,
        kind: str = "connectivity",
        prompt: str | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        result = await self.gateway.test_provider(
            provider_id,
            kind=kind,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            operation_id=operation_id,
        )
        await write_audit(
            self.database,
            action="provider.llm.test",
            target_type="llm_provider",
            target_id=provider_id,
            details={
                "kind": kind,
                "outcome": result.outcome,
                "ok": result.ok,
                "is_mock": result.is_mock,
                "error_code": result.error_code,
            },
        )
        return result.model_dump(mode="json")

    async def cancel_provider_operation(self, provider_id: str, operation_id: str) -> dict[str, Any]:
        found = self.gateway.cancel_operation(provider_id, operation_id)
        await write_audit(
            self.database,
            action="provider.llm.cancel",
            target_type="llm_provider",
            target_id=provider_id,
            details={"operation_id": operation_id, "found": found},
        )
        return {
            "found": found,
            "operation_id": operation_id,
            "message": (
                "已请求取消本地等待；无法保证服务商停止生成或停止计费。"
                if found
                else "未找到进行中的本地操作；它可能已完成、已取消或服务已重启。"
            ),
        }

    # ------------------------------------------------------------------ 媒体
    async def list_media_providers(self) -> list[dict[str, Any]]:
        return [redact_value(entry.public()) for entry in self.registry.list_entries()]

    async def _persist_media_provider(
        self,
        entry: Any,
        *,
        enabled: bool | None = None,
        status: str | None = None,
        health_status: str | None = None,
        last_error: str | None = None,
        last_health_check_at: Any = None,
    ) -> None:
        """媒体 Provider 状态持久化。只在显式传入时覆盖字段；未知历史 Provider 不凭空注册。"""
        async with self.database.session() as session:
            record = await session.get(MediaProviderState, entry.provider_id)
            if record is None:
                record = MediaProviderState(
                    id=entry.provider_id,
                    provider_type=entry.provider_type,
                    name=entry.name,
                    version=entry.version,
                    capabilities_json=list(entry.capabilities),
                    config_schema_json=dict(entry.config_schema),
                    enabled=bool(enabled if enabled is not None else entry.enabled),
                    status=status or entry.status,
                    health_status=health_status or entry.health_status,
                    is_mock=bool(entry.is_mock),
                    planned=bool(entry.planned),
                )
                session.add(record)
            if enabled is not None:
                record.enabled = bool(enabled)
            if status is not None:
                record.status = status
            if health_status is not None:
                record.health_status = health_status
            if last_error is not None or health_status is not None:
                record.last_error = last_error
            if last_health_check_at is not None:
                record.last_health_check_at = last_health_check_at
            await session.commit()

    async def load_media_provider_state(self) -> None:
        """启动时加载已持久化的媒体 Provider 状态；未知 Provider 只告警忽略。"""
        try:
            async with self.database.session() as session:
                records = list((await session.execute(select(MediaProviderState))).scalars())
        except Exception:
            logger.exception("读取媒体 Provider 状态失败，使用默认状态")
            return
        for record in records:
            entry = self.registry.get(record.id)
            if entry is None:
                logger.warning(
                    "忽略未知媒体 Provider 持久化记录",
                    extra={"provider_id": record.id, "provider_type": record.provider_type},
                )
                continue
            if entry.planned or entry.provider is None:
                continue
            entry.enabled = bool(record.enabled)
            entry.health_status = record.health_status or "unknown"
            if entry.enabled:
                entry.status = "available" if entry.health_status != "unhealthy" else "error"
            else:
                entry.status = "disabled"
            entry.last_error = record.last_error
            entry.last_health_check_at = record.last_health_check_at

    @staticmethod
    def _provider_capabilities(entry: Any) -> list[str]:
        """Provider 类型覆盖的能力，加上显式声明的能力；去重并保持固定顺序。"""
        capabilities = {
            capability for capability, provider_type in CAPABILITY_TYPES.items() if provider_type == entry.provider_type
        }
        capabilities.update(item for item in entry.capabilities if item in CAPABILITY_TYPES)
        return sorted(capabilities)

    async def set_media_provider_enabled(
        self, provider_id: str, enabled: bool, *, actor: str = "local-admin"
    ) -> dict[str, Any]:
        # 先写数据库；失败时内存状态保持不变。
        entry = self.registry.require(provider_id)
        if entry.planned or entry.provider is None:
            self.registry.set_enabled(provider_id, enabled)  # 统一抛出中文错误
        provider_capabilities = self._provider_capabilities(entry)
        status = "disabled" if not enabled else "available"
        try:
            await self._persist_media_provider(entry, enabled=enabled, status=status, last_error=None)
        except Exception as exc:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "媒体 Provider 状态保存失败，未修改内存状态。",
                status_code=500,
            ) from exc
        entry = self.registry.set_enabled(provider_id, enabled)
        if enabled:
            await self.registry.health_check(provider_id)
            try:
                await self._persist_media_provider(
                    entry,
                    enabled=entry.enabled,
                    status=entry.status,
                    health_status=entry.health_status,
                    last_error=entry.last_error,
                    last_health_check_at=entry.last_health_check_at,
                )
            except Exception:
                logger.exception("媒体 Provider 健康状态持久化失败", extra={"provider_id": provider_id})
        cancelled_jobs = 0
        cancelled_capabilities: list[str] = []
        cancellation_error: str | None = None
        if not enabled and self.media_jobs is not None:
            # 只在停用后该能力已无任何可用 Provider 时取消，避免误伤备用 Provider 的任务。
            cancelled_capabilities = [
                capability for capability in provider_capabilities if not self.registry.available_for(capability)
            ]
            if cancelled_capabilities:
                try:
                    result = await self.media_jobs.cancel_jobs_for_unavailable_capabilities(
                        cancelled_capabilities,
                        reason=f"媒体 Provider「{entry.name}」已停用，任务已取消。",
                    )
                    cancelled_jobs = int(result.get("cancelled", 0))
                except Exception as exc:
                    # 取消失败不能让停用本身回滚，但必须如实记录，不能静默。
                    cancellation_error = type(exc).__name__
                    logger.exception("停用媒体 Provider 时取消任务失败", extra={"provider_id": provider_id})
        details: dict[str, Any] = {
            "enabled": enabled,
            "is_mock": entry.is_mock,
            "cancelled_jobs": cancelled_jobs,
            "cancelled_capabilities": cancelled_capabilities,
        }
        if cancellation_error:
            details["cancellation_error"] = cancellation_error
        await write_audit(
            self.database,
            action="provider.media.toggle",
            target_type="media_provider",
            target_id=provider_id,
            details=details,
            actor=actor,
        )
        return {
            **redact_value(entry.public()),
            "cancelled_jobs": cancelled_jobs,
            "cancelled_capabilities": cancelled_capabilities,
            "cancellation_error": cancellation_error,
        }

    async def test_media_provider(self, provider_id: str) -> dict[str, Any]:
        entry = self.registry.require(provider_id)
        snapshot = (entry.enabled, entry.status, entry.health_status, entry.last_error, entry.last_health_check_at)
        entry = await self.registry.health_check(provider_id)
        try:
            await self._persist_media_provider(
                entry,
                status=entry.status,
                health_status=entry.health_status,
                last_error=entry.last_error,
                last_health_check_at=entry.last_health_check_at,
            )
        except Exception as exc:
            entry.enabled, entry.status, entry.health_status, entry.last_error, entry.last_health_check_at = snapshot
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "媒体 Provider 健康状态保存失败，内存状态已回滚。",
                status_code=500,
            ) from exc
        await write_audit(
            self.database,
            action="provider.media.test",
            target_type="media_provider",
            target_id=provider_id,
            details={"health_status": entry.health_status},
        )
        return redact_value(entry.public())

    async def capability_overview(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        checked_at = iso_utc(utcnow())
        for capability, provider_type in CAPABILITY_TYPES.items():
            able = self.registry.available_for(capability)
            entries = self.registry.list_entries(provider_type)
            if able:
                state = "mock_only" if all(item.is_mock for item in able) else "available"
            elif not [entry for entry in entries if not entry.planned]:
                state = "planned"
            elif capability in JOB_EXECUTABLE_CAPABILITIES:
                # 有可执行实现但尚未启用，属于 unconfigured；不能谎报为 planned。
                state = "unconfigured"
            elif not any(not entry.is_mock for entry in entries if not entry.planned):
                # 仅有 Mock 契约、没有真实实现且任务队列不会执行时，如实标为 planned。
                state = "planned"
            else:
                state = "unconfigured"
            execution = "job" if capability in JOB_EXECUTABLE_CAPABILITIES else "contract_only"
            note = {
                "available": "已启用真实 Provider。",
                "mock_only": "当前仅启用 Mock Provider，结果为模拟，不代表真实识别。",
                "unconfigured": "尚未启用该能力的 Provider，AI 不会看到或听到真实内容。",
                "planned": "该能力仅为规划占位，当前版本不可用。",
            }[state]
            if execution == "contract_only":
                note += " 当前仅有接口契约与 Mock，任务队列不会执行该能力。"
            next_step = {
                "available": "可继续使用；停用会立即取消该能力下排队与运行中的任务。",
                "mock_only": "Mock 结果只用于流程验证；需要真实识别时请配置并启用真实 Provider。",
                "unconfigured": "先在能力中心启用 Mock 验证流程，或配置真实 Provider。",
                "planned": "当前版本不可用；不要将其加入业务配置或对外宣称已支持。",
            }[state]
            result.append(
                {
                    "capability": capability,
                    "provider_type": provider_type,
                    "state": state,
                    "execution": execution,
                    "source": "provider_registry",
                    "checked_at": checked_at,
                    "available_provider_ids": [item.provider_id for item in able],
                    "enabled_provider_ids": [entry.provider_id for entry in entries if entry.enabled],
                    "providers": [redact_value(entry.public()) for entry in entries],
                    "last_error": next((entry.last_error for entry in entries if entry.last_error), None),
                    "note": note,
                    "next_step": next_step,
                }
            )
        return result
