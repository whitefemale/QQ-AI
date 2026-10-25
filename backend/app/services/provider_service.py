"""模型 Provider 与媒体能力管理。所有密钥只返回掩码。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from sqlalchemy import or_, select

from app.adapters.llm.anthropic_native import DEFAULT_BASE_URL as DEFAULT_ANTHROPIC_BASE_URL
from app.budgets.service import provider_pricing_state
from app.core.errors import AppError, ErrorCode
from app.core.security import CredentialCipher, redact_value
from app.core.time import iso_utc
from app.db.session import Database
from app.models.group import Group
from app.models.provider import LLMProvider
from app.pipeline.llm_gateway import LLMGateway
from app.providers.registry import CAPABILITY_TYPES, ProviderRegistry
from app.services.audit import write_audit

SUPPORTED_LLM_TYPES = {"mock", "openai_compatible", "anthropic_native"}
REMOTE_LLM_TYPES = {"openai_compatible", "anthropic_native"}


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


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
    ) -> None:
        self.database = database
        self.cipher = cipher
        self.gateway = gateway
        self.registry = registry

    # ------------------------------------------------------------------ LLM
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
            "config": redact_value(dict(record.config_json or {})),
            "last_error": record.last_error,
            "last_tested_at": iso_utc(record.last_tested_at),
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
        base_url = _clean(payload.get("base_url"), 512) or None
        if provider_type in REMOTE_LLM_TYPES:
            if provider_type == "anthropic_native" and not base_url:
                base_url = DEFAULT_ANTHROPIC_BASE_URL
            if not base_url:
                raise AppError(ErrorCode.VALIDATION_ERROR, "请填写 Base URL。", status_code=400)
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "Base URL 必须为有效的 http:// 或 https:// 地址。",
                    status_code=400,
                )
            if not _clean(payload.get("model"), 128):
                raise AppError(ErrorCode.VALIDATION_ERROR, "请填写模型 ID。", status_code=400)
        return {
            "provider_type": provider_type,
            "base_url": base_url,
            "model": _clean(payload.get("model"), 128) or ("mock-model" if provider_type == "mock" else None),
        }

    async def create_llm_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = _clean(payload.get("name"), 128)
        if not name:
            raise AppError(ErrorCode.VALIDATION_ERROR, "Provider 名称不能为空。", status_code=400)
        fields = self._validate_llm_fields(payload)
        token = payload.get("api_key")
        if token is not None and not isinstance(token, str):
            raise AppError(ErrorCode.VALIDATION_ERROR, "API Key 必须为字符串。", status_code=400)
        api_key = token.strip() if isinstance(token, str) else ""
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
            merged = {
                "provider_type": record.provider_type,
                "base_url": record.base_url,
                "model": record.model,
                **payload,
            }
            if any(key in payload for key in ("provider_type", "base_url", "model")):
                fields = self._validate_llm_fields(merged)
                record.provider_type = fields["provider_type"]
                record.base_url = fields["base_url"]
                record.model = fields["model"]
                record.status = "available" if fields["provider_type"] == "mock" else "configured"
            if "name" in payload:
                name = _clean(payload.get("name"), 128)
                if not name:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "Provider 名称不能为空。", status_code=400)
                record.name = name
            token = payload.get("api_key")
            if isinstance(token, str):
                record.api_key_encrypted = self.cipher.encrypt(token.strip()) if token.strip() else None
            if "timeout_seconds" in payload:
                record.timeout_seconds = _number(payload.get("timeout_seconds"), record.timeout_seconds, 1.0, 300.0)
            if "max_output_tokens" in payload:
                record.max_output_tokens = int(
                    _number(payload.get("max_output_tokens"), record.max_output_tokens, 1, 32000)
                )
            if "temperature" in payload:
                record.temperature = _number(payload.get("temperature"), record.temperature, 0.0, 2.0)
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

    async def test_llm_provider(self, provider_id: str) -> dict[str, Any]:
        result = await self.gateway.test_provider(provider_id)
        await write_audit(
            self.database,
            action="provider.llm.test",
            target_type="llm_provider",
            target_id=provider_id,
            details={"ok": result.ok, "error_code": result.error_code},
        )
        return result.model_dump()

    # ------------------------------------------------------------------ 媒体
    async def list_media_providers(self) -> list[dict[str, Any]]:
        return [redact_value(entry.public()) for entry in self.registry.list_entries()]

    async def set_media_provider_enabled(self, provider_id: str, enabled: bool) -> dict[str, Any]:
        entry = self.registry.set_enabled(provider_id, enabled)
        if enabled:
            await self.registry.health_check(provider_id)
        await write_audit(
            self.database,
            action="provider.media.toggle",
            target_type="media_provider",
            target_id=provider_id,
            details={"enabled": enabled, "is_mock": entry.is_mock},
        )
        return redact_value(entry.public())

    async def test_media_provider(self, provider_id: str) -> dict[str, Any]:
        entry = await self.registry.health_check(provider_id)
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
        for capability, provider_type in CAPABILITY_TYPES.items():
            able = self.registry.available_for(capability)
            entries = self.registry.list_entries(provider_type)
            if able:
                state = "mock_only" if all(item.is_mock for item in able) else "available"
            elif any(entry.planned for entry in entries):
                state = "planned"
            else:
                state = "unconfigured"
            result.append(
                {
                    "capability": capability,
                    "provider_type": provider_type,
                    "state": state,
                    "available_provider_ids": [item.provider_id for item in able],
                    "providers": [redact_value(entry.public()) for entry in entries],
                    "note": {
                        "available": "已启用真实 Provider。",
                        "mock_only": "当前仅启用 Mock Provider，结果为模拟，不代表真实识别。",
                        "unconfigured": "尚未启用该能力的 Provider，AI 不会看到或听到真实内容。",
                        "planned": "该能力仅为规划占位，当前版本不可用。",
                    }[state],
                }
            )
        return result
