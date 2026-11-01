"""QQ 账号与连接器实例管理：凭证加密、状态展示、测试与连接操作。"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.qq.mock import MockQQAdapter
from app.adapters.qq.onebot11 import validate_onebot_endpoints
from app.core.errors import AppError, ErrorCode, planned
from app.core.security import CredentialCipher, redact_value
from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.media.service import MediaService
from app.models.account import Account, AdapterInstance
from app.models.group import Group, Member
from app.models.media import MediaAsset
from app.models.memory import Memory, MemoryCandidate
from app.models.message import Message, OutboxMessage
from app.services.adapter_manager import AdapterManager, heartbeat_age_seconds
from app.services.audit import write_audit
from app.services.connection_diagnostics import failed_report
from app.services.memory_service import MemoryService
from app.services.persona_store import PersonaStore

logger = logging.getLogger(__name__)

SUPPORTED_CONNECTION_MODES = {"mock", "onebot11"}
_MAX_ENDPOINT = 512


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _bool(value: Any, default: bool = False) -> bool:
    return default if value is None else bool(value)


class AccountService:
    def __init__(
        self,
        database: Database,
        cipher: CredentialCipher,
        manager: AdapterManager,
        personas: PersonaStore,
        memories: MemoryService,
        media: MediaService,
    ) -> None:
        self.database = database
        self.cipher = cipher
        self.manager = manager
        self.personas = personas
        self.memories = memories
        self.media = media

    # ------------------------------------------------------------------ 查询
    async def list_accounts(self) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            accounts = list((await session.execute(select(Account).order_by(Account.created_at))).scalars())
            return [await self._public(account) for account in accounts]

    async def get_account(self, account_id: str) -> dict[str, Any]:
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在或已被删除。", status_code=404)
            return await self._public(account)

    async def _instance_public(self, instance: AdapterInstance) -> dict[str, Any]:
        live = await self.manager.public_health(instance.id)
        return {
            "id": instance.id,
            "account_id": instance.account_id,
            "name": instance.name,
            "connection_mode": instance.connection_mode,
            "endpoint": instance.endpoint,
            "api_endpoint": instance.api_endpoint,
            "token_configured": bool(instance.token_encrypted),
            "token_masked": self.cipher.mask_encrypted(instance.token_encrypted) if instance.token_encrypted else "",
            "allow_remote": instance.allow_remote,
            "auto_connect": instance.auto_connect,
            "enabled": instance.enabled,
            "capabilities": dict(instance.capabilities_json or {}),
            "status": instance.status,
            "last_heartbeat_at": iso_utc(instance.last_heartbeat_at),
            "last_received_at": iso_utc(instance.last_received_at),
            "last_sent_at": iso_utc(instance.last_sent_at),
            "heartbeat_age_seconds": heartbeat_age_seconds(instance.last_heartbeat_at),
            "last_error_code": instance.last_error_code,
            "last_error_message": instance.last_error_message,
            "live_health": redact_value(live) if live else None,
            "created_at": iso_utc(instance.created_at),
            "updated_at": iso_utc(instance.updated_at),
        }

    async def _public(self, account: Account) -> dict[str, Any]:
        instances = [await self._instance_public(item) for item in account.instances]
        instances.sort(key=lambda item: (not item["enabled"], str(item["name"])))
        return {
            "id": account.id,
            "display_name": account.display_name,
            "platform": account.platform,
            "adapter_type": account.adapter_type,
            "self_platform_user_id": account.self_platform_user_id,
            "enabled": account.enabled,
            "allow_private": account.allow_private,
            "status": account.status,
            "notes": account.notes,
            "instances": instances,
            "created_at": iso_utc(account.created_at),
            "updated_at": iso_utc(account.updated_at),
        }

    # ------------------------------------------------------------------ 账号
    async def create_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        display_name = _clean(payload.get("display_name"), 128)
        if not display_name:
            raise AppError(ErrorCode.VALIDATION_ERROR, "账号名称不能为空。", status_code=400)
        instance_payload = payload.get("instance")
        account = Account(
            display_name=display_name,
            platform="qq",
            adapter_type="mock",
            enabled=_bool(payload.get("enabled"), True),
            allow_private=_bool(payload.get("allow_private"), False),
            status="disconnected",
            notes=_clean(payload.get("notes"), 2000) or None,
        )
        async with self.database.session() as session:
            session.add(account)
            await session.flush()
            if isinstance(instance_payload, dict) and instance_payload:
                instance = await self._build_instance(session, account, instance_payload)
                account.adapter_type = instance.connection_mode
            await session.commit()
            account_id = account.id
        await write_audit(
            self.database,
            action="account.create",
            target_type="account",
            target_id=account_id,
            details={"display_name": display_name, "instance_created": bool(instance_payload)},
        )
        return await self.get_account(account_id)

    async def update_account(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在或已被删除。", status_code=404)
            changed: list[str] = []
            if "display_name" in payload:
                name = _clean(payload.get("display_name"), 128)
                if not name:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "账号名称不能为空。", status_code=400)
                account.display_name = name
                changed.append("display_name")
            if "enabled" in payload:
                account.enabled = bool(payload.get("enabled"))
                changed.append("enabled")
            if "allow_private" in payload:
                account.allow_private = bool(payload.get("allow_private"))
                changed.append("allow_private")
            if "notes" in payload:
                account.notes = _clean(payload.get("notes"), 2000) or None
                changed.append("notes")
            disabled = "enabled" in payload and not account.enabled
            await session.commit()
        if disabled:
            await self.manager.disconnect_account(account_id)
            async with self.database.session() as session:
                current = await session.get(Account, account_id)
                if current is not None:
                    current.status = "disconnected"
                    for instance in current.instances:
                        instance.status = "disconnected"
                    await session.commit()
        await write_audit(
            self.database,
            action="account.update",
            target_type="account",
            target_id=account_id,
            details={"changed_fields": changed},
        )
        return await self.get_account(account_id)

    async def delete_account(self, account_id: str, *, actor: str = "local-admin") -> None:
        """删除账号及其关联数据；媒体只清理不再被其他消息引用的资产。"""
        await self.manager.disconnect_account(account_id)
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在或已被删除。", status_code=404)
            name = account.display_name
            message_rows = list(
                (
                    await session.execute(
                        select(Message.id, Message.segments_json).where(Message.account_id == account_id)
                    )
                ).all()
            )
            message_ids = {str(row.id) for row in message_rows}
            media_refs: set[str] = set()
            for row in message_rows:
                for segment in row.segments_json or []:
                    if isinstance(segment, dict):
                        ref = segment.get("media_ref")
                        if isinstance(ref, str) and ref.strip():
                            media_refs.add(ref.strip())
            media_asset_ids = list(
                (
                    await session.execute(
                        select(MediaAsset.id).where(
                            MediaAsset.account_id == account_id,
                            MediaAsset.deleted_at.is_(None),
                        )
                    )
                ).scalars()
            )
            counts = {
                "groups": int(
                    await session.scalar(select(func.count(Group.id)).where(Group.account_id == account_id)) or 0
                ),
                "members": int(
                    await session.scalar(select(func.count(Member.id)).where(Member.account_id == account_id)) or 0
                ),
                "messages": len(message_ids),
                "memories": int(
                    await session.scalar(select(func.count(Memory.id)).where(Memory.account_id == account_id)) or 0
                ),
                "memory_candidates": int(
                    await session.scalar(
                        select(func.count(MemoryCandidate.id)).where(MemoryCandidate.account_id == account_id)
                    )
                    or 0
                ),
                "outbox_messages": int(
                    await session.scalar(
                        select(func.count(OutboxMessage.id)).where(OutboxMessage.account_id == account_id)
                    )
                    or 0
                ),
                "media_assets": len(media_asset_ids),
            }
        if message_ids:
            # 先擦除人格证据与记忆来源，避免删除账号后留下指向已删消息的引用。
            await self.personas.prune_evidence(message_ids, actor=actor)
            await self.memories.scrub_source_message_ids(message_ids, actor=actor)
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在或已被删除。", status_code=404)
            await session.delete(account)
            await session.commit()
        media_deleted = 0
        media_skipped = 0
        media_errors = 0
        for media_id in media_asset_ids:
            try:
                if await self.media.delete(str(media_id), protect_referenced=True):
                    media_deleted += 1
                else:
                    media_skipped += 1
            except Exception as exc:  # noqa: BLE001 - 媒体清理失败不能掩盖账号已删除
                media_errors += 1
                logger.warning("删除账号媒体失败", extra={"media_id": str(media_id), "reason": type(exc).__name__})
        await write_audit(
            self.database,
            action="account.delete",
            target_type="account",
            target_id=account_id,
            details={
                "display_name": name,
                **counts,
                "media_deleted": media_deleted,
                "media_skipped_shared": media_skipped,
                "media_errors": media_errors,
                "media_refs": len(media_refs),
            },
            actor=actor,
        )

    # ------------------------------------------------------------------ 实例
    def _normalize_instance_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        mode = str(payload.get("connection_mode") or "mock").strip()
        if mode in {"official", "official_bot"}:
            raise planned("官方 QQ 机器人接入")
        if mode not in SUPPORTED_CONNECTION_MODES:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "连接方式必须为 mock 或 onebot11。",
                status_code=400,
            )
        allow_remote = bool(payload.get("allow_remote", False))
        endpoint = _clean(payload.get("endpoint"), _MAX_ENDPOINT) or None
        api_endpoint = _clean(payload.get("api_endpoint"), _MAX_ENDPOINT) or None
        if mode == "mock":
            endpoint = None
            api_endpoint = None
        else:
            if not endpoint:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "OneBot 11 模式必须填写 WebSocket 地址。",
                    status_code=400,
                )
            endpoint, api_endpoint = validate_onebot_endpoints(
                endpoint,
                api_endpoint,
                allow_remote=allow_remote,
            )
        token = payload.get("token")
        if token is not None and not isinstance(token, str):
            raise AppError(ErrorCode.VALIDATION_ERROR, "Token 必须为字符串。", status_code=400)
        return {
            "mode": mode,
            "endpoint": endpoint,
            "api_endpoint": api_endpoint,
            "allow_remote": allow_remote,
            "token": token.strip() if isinstance(token, str) else None,
        }

    async def _build_instance(
        self,
        session: AsyncSession,
        account: Account,
        payload: dict[str, Any],
    ) -> AdapterInstance:
        normalized = self._normalize_instance_payload(payload)
        name = _clean(payload.get("name"), 128) or "默认连接"
        token = normalized["token"]
        instance = AdapterInstance(
            account_id=account.id,
            name=name,
            connection_mode=normalized["mode"],
            endpoint=normalized["endpoint"],
            api_endpoint=normalized["api_endpoint"],
            token_encrypted=self.cipher.encrypt(token) if token else None,
            allow_remote=normalized["allow_remote"],
            auto_connect=_bool(payload.get("auto_connect"), True),
            enabled=_bool(payload.get("enabled"), True),
            status="unconfigured",
            capabilities_json={},
        )
        session.add(instance)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise AppError(
                ErrorCode.CONFLICT,
                "同一账号下已存在同名连接器实例。",
                status_code=409,
            ) from exc
        return instance

    async def add_instance(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在或已被删除。", status_code=404)
            instance = await self._build_instance(session, account, payload)
            account.adapter_type = instance.connection_mode
            await session.commit()
            instance_id = instance.id
        await write_audit(
            self.database,
            action="account.instance.create",
            target_type="adapter_instance",
            target_id=instance_id,
            details={"account_id": account_id, "mode": payload.get("connection_mode")},
        )
        data = await self.get_account(account_id)
        return next(item for item in data["instances"] if item["id"] == instance_id)

    async def update_instance(
        self,
        account_id: str,
        instance_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        await self.manager.forget_instance(instance_id)
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在或已被删除。", status_code=404)
            instance = await session.get(AdapterInstance, instance_id)
            if instance is None or instance.account_id != account_id:
                raise AppError(ErrorCode.ADAPTER_NOT_FOUND, "连接器实例不存在。", status_code=404)
            merged = {
                "connection_mode": instance.connection_mode,
                "endpoint": instance.endpoint,
                "api_endpoint": instance.api_endpoint,
                "allow_remote": instance.allow_remote,
                "name": instance.name,
                "auto_connect": instance.auto_connect,
                "enabled": instance.enabled,
            }
            for key in ("connection_mode", "endpoint", "api_endpoint", "allow_remote", "auto_connect", "enabled"):
                if key in payload:
                    merged[key] = payload[key]
            normalized = self._normalize_instance_payload(merged)
            instance.connection_mode = normalized["mode"]
            instance.endpoint = normalized["endpoint"]
            instance.api_endpoint = normalized["api_endpoint"]
            instance.allow_remote = normalized["allow_remote"]
            if "name" in payload:
                name = _clean(payload.get("name"), 128)
                if not name:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "连接器名称不能为空。", status_code=400)
                instance.name = name
            if "auto_connect" in payload:
                instance.auto_connect = bool(payload.get("auto_connect"))
            if "enabled" in payload:
                instance.enabled = bool(payload.get("enabled"))
            token = payload.get("token")
            if isinstance(token, str):
                instance.token_encrypted = self.cipher.encrypt(token.strip()) if token.strip() else None
            instance.status = "disconnected"
            instance.capabilities_json = {}
            instance.last_error_code = None
            instance.last_error_message = None
            account.adapter_type = instance.connection_mode
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise AppError(
                    ErrorCode.CONFLICT,
                    "同一账号下已存在同名连接器实例。",
                    status_code=409,
                ) from exc
        await write_audit(
            self.database,
            action="account.instance.update",
            target_type="adapter_instance",
            target_id=instance_id,
            details={"account_id": account_id, "changed_fields": sorted(payload.keys())},
        )
        data = await self.get_account(account_id)
        return next(item for item in data["instances"] if item["id"] == instance_id)

    async def delete_instance(self, account_id: str, instance_id: str) -> None:
        await self.manager.forget_instance(instance_id)
        async with self.database.session() as session:
            instance = await session.get(AdapterInstance, instance_id)
            if instance is None or instance.account_id != account_id:
                raise AppError(ErrorCode.ADAPTER_NOT_FOUND, "连接器实例不存在。", status_code=404)
            await session.delete(instance)
            account = await session.get(Account, account_id)
            if account is not None:
                await session.flush()
                remaining = [item for item in account.instances if item.id != instance_id]
                if not remaining:
                    account.status = "disconnected"
            await session.commit()
        await write_audit(
            self.database,
            action="account.instance.delete",
            target_type="adapter_instance",
            target_id=instance_id,
            details={"account_id": account_id},
        )

    async def connect_instance(self, account_id: str, instance_id: str) -> dict[str, Any]:
        await self._require_instance(account_id, instance_id)
        adapter = await self.manager.connect_instance(instance_id)
        await write_audit(
            self.database,
            action="account.instance.connect",
            target_type="adapter_instance",
            target_id=instance_id,
            details={"account_id": account_id, "status": adapter.status},
        )
        data = await self.get_account(account_id)
        return next(item for item in data["instances"] if item["id"] == instance_id)

    async def disconnect_instance(self, account_id: str, instance_id: str) -> dict[str, Any]:
        await self._require_instance(account_id, instance_id)
        await self.manager.disconnect_instance(instance_id)
        await write_audit(
            self.database,
            action="account.instance.disconnect",
            target_type="adapter_instance",
            target_id=instance_id,
            details={"account_id": account_id},
        )
        data = await self.get_account(account_id)
        return next(item for item in data["instances"] if item["id"] == instance_id)

    async def _require_instance(self, account_id: str, instance_id: str) -> AdapterInstance:
        async with self.database.session() as session:
            instance = await session.get(AdapterInstance, instance_id)
            if instance is None or instance.account_id != account_id:
                raise AppError(ErrorCode.ADAPTER_NOT_FOUND, "连接器实例不存在。", status_code=404)
            return instance

    async def test_saved_instance(
        self,
        account_id: str,
        instance_id: str,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        instance = await self._require_instance(account_id, instance_id)
        overrides = overrides or {}
        mode = str(overrides.get("connection_mode") or instance.connection_mode)
        endpoint = overrides.get("endpoint", instance.endpoint)
        api_endpoint = overrides.get("api_endpoint", instance.api_endpoint)
        allow_remote = bool(overrides.get("allow_remote", instance.allow_remote))
        token = overrides.get("token")
        if not isinstance(token, str):
            token = self.cipher.decrypt(instance.token_encrypted) if instance.token_encrypted else None
        else:
            token = token.strip() or None
        result = await self.manager.test_connection(
            connection_mode=mode,
            endpoint=endpoint,
            api_endpoint=api_endpoint,
            token=token,
            allow_remote=allow_remote,
        )
        await write_audit(
            self.database,
            action="account.instance.test",
            target_type="adapter_instance",
            target_id=instance_id,
            details={
                "account_id": account_id,
                "mode": mode,
                "ok": result.get("ok"),
                "state": result.get("state"),
            },
        )
        return redact_value(result)

    async def test_unsaved_connection(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            normalized = self._normalize_instance_payload(payload)
        except AppError as exc:
            result = failed_report(
                connection_mode=_clean(payload.get("connection_mode"), 32) or "onebot11",
                started_at=utcnow(),
                error_code=exc.code,
                error_message=exc.message,
                config_error=True,
            ).model_dump(mode="json")
            await write_audit(
                self.database,
                action="account.instance.test_unsaved",
                target_type="adapter_instance",
                details={"ok": False, "state": result["state"]},
            )
            return redact_value(result)
        result = await self.manager.test_connection(
            connection_mode=normalized["mode"],
            endpoint=normalized["endpoint"],
            api_endpoint=normalized["api_endpoint"],
            token=normalized["token"],
            allow_remote=normalized["allow_remote"],
        )
        await write_audit(
            self.database,
            action="account.instance.test_unsaved",
            target_type="adapter_instance",
            details={"mode": normalized["mode"], "ok": result.get("ok"), "state": result.get("state")},
        )
        return redact_value(result)

    async def require_confirmed_identity(
        self,
        account_id: str,
        instance_id: str,
        confirm_self_user_id: str | None,
    ) -> dict[str, Any]:
        """导入群列表等真实操作前，必须由用户确认当前登录身份。

        身份只能来自在线适配器报告的 ``self_platform_user_id``；Mock 永远拒绝。
        """
        instance = await self._require_instance(account_id, instance_id)
        confirmed = str(confirm_self_user_id or "").strip()
        if not confirmed:
            raise AppError(
                ErrorCode.CONNECTOR_IDENTITY_MISMATCH,
                "请先确认当前登录的 QQ 号（confirm_self_user_id）后再导入真实群列表。",
                status_code=400,
            )
        adapter = self.manager.get_adapter(instance_id)
        if adapter is None:
            raise AppError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                "请先连接该连接器并完成身份验证。",
                status_code=409,
            )
        if isinstance(adapter, MockQQAdapter) or instance.connection_mode == "mock":
            raise AppError(
                ErrorCode.ADAPTER_UNSUPPORTED_OPERATION,
                "Mock 模式没有真实 QQ 身份，不能导入真实群列表或确认身份。",
                status_code=400,
            )
        if adapter.status == "connected_unverified":
            raise AppError(
                ErrorCode.ADAPTER_IDENTITY_UNVERIFIED,
                "连接器已连接但身份尚未验证；请先完成 WebSocket 身份验证。",
                status_code=409,
            )
        if adapter.status != "online":
            raise AppError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                "连接器当前不在线，无法确认身份。",
                status_code=409,
            )
        expected = str(adapter.self_platform_user_id or "").strip()
        if not expected:
            raise AppError(
                ErrorCode.ADAPTER_IDENTITY_UNVERIFIED,
                "连接器尚未返回登录账号，无法确认身份。",
                status_code=409,
            )
        if not hmac.compare_digest(expected, confirmed):
            raise AppError(
                ErrorCode.CONNECTOR_IDENTITY_MISMATCH,
                "填写的 QQ 号与连接器当前登录身份不一致。",
                status_code=409,
            )
        return {"user_id": expected, "instance": instance}

    async def fetch_connector_groups(self, account_id: str, instance_id: str) -> dict[str, Any]:
        await self._require_instance(account_id, instance_id)
        adapter = self.manager.get_adapter(instance_id)
        if adapter is None:
            raise AppError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                "请先连接该连接器，再获取群列表。",
                status_code=409,
            )
        if adapter.status == "connected_unverified":
            raise AppError(
                ErrorCode.ADAPTER_IDENTITY_UNVERIFIED,
                "连接器已连接，但 QQ 登录身份尚未验证；请先完成身份验证后再获取群列表。",
                status_code=409,
            )
        if adapter.status != "online":
            raise AppError(
                ErrorCode.ADAPTER_UNAVAILABLE,
                "连接器当前不在线，请先连接并确认身份已验证。",
                status_code=409,
            )
        groups = await adapter.get_group_list()
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            self_id = account.self_platform_user_id if account else adapter.self_platform_user_id
        return {
            "instance_id": instance_id,
            "fetched_at": iso_utc(utcnow()),
            "self_platform_user_id": self_id,
            "groups": [
                {
                    "platform_group_id": str(item.get("group_id")),
                    "name": _clean(item.get("group_name"), 128) or None,
                }
                for item in groups
                if item.get("group_id") is not None
            ],
        }
