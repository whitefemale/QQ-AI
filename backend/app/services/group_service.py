"""群白名单与群级配置管理。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.time import get_zone, iso_utc, parse_hhmm, utcnow
from app.db.session import Database
from app.models.account import Account
from app.models.group import Group, Member
from app.models.memory import Memory, MemoryCandidate
from app.models.message import Message, OutboxMessage
from app.models.persona import Persona
from app.models.provider import LLMProvider
from app.pipeline.policy import DEFAULT_RATE_LIMITS, SUPPORTED_REPLY_MODES
from app.services.audit import write_audit

_MAX_NAME = 256
_MAX_RULES = 4000


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _bool(value: Any, default: bool = False) -> bool:
    return default if value is None else bool(value)


def _clean_list(value: Any, *, limit: int = 50, item_limit: int = 64) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = _clean(item, item_limit)
        if text and text not in result:
            result.append(text)
    return result


def sanitize_quiet_hours(value: Any, default_timezone: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    enabled = bool(value.get("enabled"))
    timezone_name = _clean(value.get("timezone"), 64) or default_timezone
    get_zone(timezone_name)
    if not enabled:
        return {"enabled": False, "timezone": timezone_name}
    start = _clean(value.get("start"), 8)
    end = _clean(value.get("end"), 8)
    if not start or not end:
        raise AppError(
            ErrorCode.QUIET_HOURS_INVALID,
            "启用安静时段时必须填写开始与结束时间（HH:MM）。",
            status_code=400,
        )
    start_time = parse_hhmm(start)
    end_time = parse_hhmm(end)
    return {
        "enabled": True,
        "start": start_time.strftime("%H:%M"),
        "end": end_time.strftime("%H:%M"),
        "timezone": timezone_name,
    }


def sanitize_rate_limits(value: Any) -> dict[str, int]:
    merged = dict(DEFAULT_RATE_LIMITS)
    if not isinstance(value, dict):
        return merged
    bounds = {
        "cooldown_seconds": (0, 3600),
        "max_replies_per_hour": (1, 1000),
        "max_replies_per_day": (1, 10000),
        "max_consecutive_replies": (1, 50),
        "max_replies_per_member_per_hour": (1, 1000),
        "max_replies_per_member_per_day": (1, 10000),
    }
    for key, (minimum, maximum) in bounds.items():
        if key not in value:
            continue
        try:
            number = int(value[key])
        except (TypeError, ValueError) as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"频率限制「{key}」必须为整数。",
                status_code=400,
            ) from exc
        merged[key] = min(max(number, minimum), maximum)
    return merged


def _optional_int(value: Any, label: str, minimum: int, maximum: int) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{label}必须为整数。", status_code=400) from exc
    if not minimum <= number <= maximum:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"{label}必须在 {minimum} 到 {maximum} 之间。",
            status_code=400,
        )
    return number


class GroupService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    @staticmethod
    def _provider_state(provider_id: str | None, provider: LLMProvider | None) -> str:
        if not provider_id:
            return "default"
        if provider is None:
            return "missing"
        if not provider.enabled:
            return "disabled"
        if provider.provider_type == "mock":
            return "mock"
        return "configured"

    async def _providers_by_ids(self, session: Any, provider_ids: list[str | None]) -> dict[str, LLMProvider]:
        ids = {provider_id for provider_id in provider_ids if provider_id}
        if not ids:
            return {}
        records = (await session.execute(select(LLMProvider).where(LLMProvider.id.in_(ids)))).scalars()
        return {record.id: record for record in records}

    async def _validate_llm_routing(
        self,
        session: Any,
        primary_id: str | None,
        fallback_id: str | None,
        *,
        validate_roles: set[str] | None = None,
    ) -> None:
        """校验群级模型绑定。

        validate_roles 用于编辑场景：只重新校验本次实际变更的角色，
        避免已绑定 Provider 事后被禁用时，管理员无法保存其他无关配置。
        """
        if fallback_id and not primary_id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "设置备用模型前必须先选择主模型。",
                status_code=400,
            )
        if primary_id and fallback_id and primary_id == fallback_id:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "主模型与备用模型不能是同一个 Provider。",
                status_code=400,
            )
        providers = await self._providers_by_ids(session, [primary_id, fallback_id])
        for role_key, role, provider_id in (
            ("primary", "主", primary_id),
            ("fallback", "备用", fallback_id),
        ):
            if not provider_id:
                continue
            if validate_roles is not None and role_key not in validate_roles:
                continue
            provider = providers.get(provider_id)
            if provider is None:
                raise AppError(
                    ErrorCode.PROVIDER_NOT_FOUND,
                    f"{role}模型 Provider 不存在。",
                    status_code=400,
                )
            if not provider.enabled:
                raise AppError(
                    ErrorCode.PROVIDER_DISABLED,
                    f"{role}模型 Provider 已禁用，请先在「模型 API」中启用。",
                    status_code=400,
                )

    def _public(
        self,
        group: Group,
        account: Account | None,
        persona_name: str | None,
        providers: dict[str, LLMProvider] | None = None,
    ) -> dict[str, Any]:
        providers = providers or {}
        primary = providers.get(group.llm_provider_id or "")
        fallback = providers.get(group.llm_fallback_provider_id or "")
        return {
            "id": group.id,
            "account_id": group.account_id,
            "account_name": account.display_name if account else None,
            "account_enabled": account.enabled if account else False,
            "platform_group_id": group.platform_group_id,
            "name": group.name,
            "enabled": group.enabled,
            "paused": group.paused,
            "reply_mode": group.reply_mode,
            "max_reply_chars": group.max_reply_chars,
            "max_reply_chars_effective": group.max_reply_chars or self.settings.max_reply_chars,
            "context_message_limit": group.context_message_limit,
            "context_message_limit_effective": group.context_message_limit or self.settings.context_message_limit,
            "persona_id": group.persona_id,
            "persona_name": persona_name,
            "llm_provider_id": group.llm_provider_id,
            "llm_provider_name": primary.name if primary else None,
            "llm_provider_type": primary.provider_type if primary else None,
            "llm_provider_state": self._provider_state(group.llm_provider_id, primary),
            "llm_fallback_provider_id": group.llm_fallback_provider_id,
            "llm_fallback_provider_name": fallback.name if fallback else None,
            "llm_fallback_provider_type": fallback.provider_type if fallback else None,
            "llm_fallback_provider_state": self._provider_state(group.llm_fallback_provider_id, fallback),
            "allow_memory": group.allow_memory,
            "auto_memory_extraction": group.auto_memory_extraction,
            "memory_extraction_last_run_at": iso_utc(group.memory_extraction_last_run_at),
            "memory_extraction_last_error": group.memory_extraction_last_error,
            "memory_extraction_watermark_at": iso_utc(group.memory_extraction_watermark_at),
            "memory_extraction_watermark_message_id": group.memory_extraction_watermark_message_id,
            "allow_tools": group.allow_tools,
            "allow_proactive": group.allow_proactive,
            "admin_user_ids": list(group.admin_user_ids_json or []),
            "quiet_hours": dict(group.quiet_hours_json or {}),
            "rate_limit": {**DEFAULT_RATE_LIMITS, **(group.rate_limit_json or {})},
            "keywords": list(group.keywords_json or []),
            "group_rules_text": group.group_rules_text,
            "timezone": group.timezone,
            "created_at": iso_utc(group.created_at),
            "updated_at": iso_utc(group.updated_at),
        }

    async def list_groups(self) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            groups = list((await session.execute(select(Group).order_by(Group.created_at))).scalars())
            accounts = {item.id: item for item in (await session.execute(select(Account))).scalars()}
            personas = {item.id: item.name for item in (await session.execute(select(Persona))).scalars()}
            providers = {item.id: item for item in (await session.execute(select(LLMProvider))).scalars()}
            return [
                self._public(
                    group,
                    accounts.get(group.account_id),
                    personas.get(group.persona_id or ""),
                    providers,
                )
                for group in groups
            ]

    async def get_group(self, group_id: str) -> dict[str, Any]:
        async with self.database.session() as session:
            group = await session.get(Group, group_id)
            if group is None:
                raise AppError(ErrorCode.NOT_FOUND, "群不存在或尚未登记。", status_code=404)
            account = await session.get(Account, group.account_id)
            persona = await session.get(Persona, group.persona_id) if group.persona_id else None
            providers = await self._providers_by_ids(session, [group.llm_provider_id, group.llm_fallback_provider_id])
            return self._public(group, account, persona.name if persona else None, providers)

    async def _persona_name(self, session: Any, persona_id: str | None) -> str | None:
        if not persona_id:
            return None
        persona = await session.get(Persona, persona_id)
        if persona is None:
            raise AppError(ErrorCode.PERSONA_NOT_FOUND, "绑定的人格不存在。", status_code=400)
        return persona.name

    async def create_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        account_id = _clean(payload.get("account_id"), 64)
        platform_group_id = _clean(payload.get("platform_group_id"), 128)
        if not account_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, "请选择账号。", status_code=400)
        if not platform_group_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, "请填写群号。", status_code=400)
        # 新群默认观察：不会生成任何回复；已有群不会被静默改写。
        reply_mode = str(payload.get("reply_mode") or "observe")
        if reply_mode not in SUPPORTED_REPLY_MODES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "回复模式无效。", status_code=400)
        timezone_name = _clean(payload.get("timezone"), 64) or self.settings.default_timezone
        get_zone(timezone_name)
        llm_provider_id = _clean(payload.get("llm_provider_id"), 64) or None
        llm_fallback_provider_id = _clean(payload.get("llm_fallback_provider_id"), 64) or None
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在。", status_code=400)
            persona_name = await self._persona_name(session, payload.get("persona_id"))
            await self._validate_llm_routing(session, llm_provider_id, llm_fallback_provider_id)
            group = Group(
                account_id=account_id,
                platform_group_id=platform_group_id,
                name=_clean(payload.get("name"), _MAX_NAME) or None,
                enabled=_bool(payload.get("enabled"), False),
                reply_mode=reply_mode,
                max_reply_chars=_optional_int(payload.get("max_reply_chars"), "群级回复字数上限", 50, 2000),
                context_message_limit=_optional_int(payload.get("context_message_limit"), "群级上下文条数", 1, 100),
                persona_id=_clean(payload.get("persona_id"), 64) or None,
                llm_provider_id=llm_provider_id,
                llm_fallback_provider_id=llm_fallback_provider_id,
                allow_memory=_bool(payload.get("allow_memory"), False),
                auto_memory_extraction=_bool(payload.get("auto_memory_extraction"), False)
                and _bool(payload.get("allow_memory"), False),
                allow_tools=_bool(payload.get("allow_tools"), False),
                allow_proactive=_bool(payload.get("allow_proactive"), False),
                admin_user_ids_json=_clean_list(payload.get("admin_user_ids"), limit=20),
                quiet_hours_json=sanitize_quiet_hours(payload.get("quiet_hours"), timezone_name),
                rate_limit_json=sanitize_rate_limits(payload.get("rate_limit")),
                keywords_json=_clean_list(payload.get("keywords"), limit=50),
                group_rules_text=_clean(payload.get("group_rules_text"), _MAX_RULES) or None,
                timezone=timezone_name,
            )
            session.add(group)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise AppError(
                    ErrorCode.CONFLICT,
                    "该群已在白名单中，请直接编辑现有记录。",
                    status_code=409,
                ) from exc
            await session.refresh(group)
            providers = await self._providers_by_ids(session, [group.llm_provider_id, group.llm_fallback_provider_id])
            public = self._public(group, account, persona_name, providers)
            group_id = group.id
        await write_audit(
            self.database,
            action="group.create",
            target_type="group",
            target_id=group_id,
            details={"account_id": account_id, "platform_group_id": platform_group_id},
        )
        return public

    async def update_group(self, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self.database.session() as session:
            group = await session.get(Group, group_id)
            if group is None:
                raise AppError(ErrorCode.NOT_FOUND, "群不存在或尚未登记。", status_code=404)
            account = await session.get(Account, group.account_id)
            if "llm_provider_id" in payload or "llm_fallback_provider_id" in payload:
                primary_id = (
                    _clean(payload.get("llm_provider_id"), 64) or None
                    if "llm_provider_id" in payload
                    else group.llm_provider_id
                )
                fallback_id = (
                    _clean(payload.get("llm_fallback_provider_id"), 64) or None
                    if "llm_fallback_provider_id" in payload
                    else group.llm_fallback_provider_id
                )
                if not primary_id and "llm_fallback_provider_id" not in payload:
                    # 清除主模型时自动解除备用模型；显式提交备用模型则视为配置错误。
                    fallback_id = None
                validate_roles: set[str] = set()
                if primary_id != group.llm_provider_id:
                    validate_roles.add("primary")
                if fallback_id != group.llm_fallback_provider_id:
                    validate_roles.add("fallback")
                await self._validate_llm_routing(
                    session,
                    primary_id,
                    fallback_id,
                    validate_roles=validate_roles,
                )
                group.llm_provider_id = primary_id
                group.llm_fallback_provider_id = fallback_id
            if "name" in payload:
                group.name = _clean(payload.get("name"), _MAX_NAME) or None
            if "enabled" in payload:
                group.enabled = bool(payload.get("enabled"))
            if "paused" in payload:
                group.paused = bool(payload.get("paused"))
            if "reply_mode" in payload:
                reply_mode = str(payload.get("reply_mode") or "")
                if reply_mode not in SUPPORTED_REPLY_MODES:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "回复模式无效。", status_code=400)
                group.reply_mode = reply_mode
            if "max_reply_chars" in payload:
                group.max_reply_chars = _optional_int(payload.get("max_reply_chars"), "群级回复字数上限", 50, 2000)
            if "context_message_limit" in payload:
                group.context_message_limit = _optional_int(
                    payload.get("context_message_limit"), "群级上下文条数", 1, 100
                )
            if "persona_id" in payload:
                persona_id = _clean(payload.get("persona_id"), 64) or None
                await self._persona_name(session, persona_id)
                group.persona_id = persona_id
            if "allow_memory" in payload:
                group.allow_memory = bool(payload.get("allow_memory"))
                if not group.allow_memory:
                    group.auto_memory_extraction = False
            if "auto_memory_extraction" in payload:
                group.auto_memory_extraction = bool(payload.get("auto_memory_extraction")) and (group.allow_memory)
            if "allow_tools" in payload:
                group.allow_tools = bool(payload.get("allow_tools"))
            if "allow_proactive" in payload:
                group.allow_proactive = bool(payload.get("allow_proactive"))
            if "admin_user_ids" in payload:
                group.admin_user_ids_json = _clean_list(payload.get("admin_user_ids"), limit=20)
            if "timezone" in payload:
                timezone_name = _clean(payload.get("timezone"), 64) or self.settings.default_timezone
                get_zone(timezone_name)
                group.timezone = timezone_name
            if "quiet_hours" in payload:
                group.quiet_hours_json = sanitize_quiet_hours(payload.get("quiet_hours"), group.timezone)
            if "rate_limit" in payload:
                group.rate_limit_json = sanitize_rate_limits(payload.get("rate_limit"))
            if "keywords" in payload:
                group.keywords_json = _clean_list(payload.get("keywords"), limit=50)
            if "group_rules_text" in payload:
                group.group_rules_text = _clean(payload.get("group_rules_text"), _MAX_RULES) or None
            await session.commit()
            await session.refresh(group)
            persona = await session.get(Persona, group.persona_id) if group.persona_id else None
            providers = await self._providers_by_ids(session, [group.llm_provider_id, group.llm_fallback_provider_id])
            public = self._public(group, account, persona.name if persona else None, providers)
        await write_audit(
            self.database,
            action="group.update",
            target_type="group",
            target_id=group_id,
            details={"changed_fields": sorted(payload.keys())},
        )
        return public

    async def set_paused(self, group_id: str, paused: bool) -> dict[str, Any]:
        data = await self.update_group(group_id, {"paused": paused})
        await write_audit(
            self.database,
            action="group.pause" if paused else "group.resume",
            target_type="group",
            target_id=group_id,
            details={},
        )
        return data

    async def delete_group(self, group_id: str, *, actor: str = "local-admin") -> None:
        """删除群配置；历史消息保留但解除关联，待发送消息取消。"""
        async with self.database.session() as session:
            group = await session.get(Group, group_id)
            if group is None:
                raise AppError(ErrorCode.NOT_FOUND, "群不存在或尚未登记。", status_code=404)
            name = group.name or group.platform_group_id
            counts = {
                "messages_retained": int(
                    await session.scalar(select(func.count(Message.id)).where(Message.group_id == group_id)) or 0
                ),
                "memories_deleted": int(
                    await session.scalar(select(func.count(Memory.id)).where(Memory.group_id == group_id)) or 0
                ),
                "memory_candidates_deleted": int(
                    await session.scalar(
                        select(func.count(MemoryCandidate.id)).where(MemoryCandidate.group_id == group_id)
                    )
                    or 0
                ),
            }
            pending = int(
                await session.scalar(
                    select(func.count(OutboxMessage.id)).where(
                        OutboxMessage.group_id == group_id,
                        OutboxMessage.status.in_(("pending", "pending_approval")),
                    )
                )
                or 0
            )
            if pending:
                # 删除群后 group_id 会被置空；必须先取消，否则 worker 仍会按 conversation_id 发送。
                await session.execute(
                    update(OutboxMessage)
                    .where(
                        OutboxMessage.group_id == group_id,
                        OutboxMessage.status.in_(("pending", "pending_approval")),
                    )
                    .values(
                        status="cancelled",
                        next_attempt_at=None,
                        last_error_code=ErrorCode.POLICY_BLOCKED,
                        last_error_message="群已删除，待发送消息已取消。",
                    )
                )
            await session.delete(group)
            await session.commit()
        await write_audit(
            self.database,
            action="group.delete",
            target_type="group",
            target_id=group_id,
            details={**counts, "outbox_cancelled": pending, "name": name},
            actor=actor,
        )

    async def import_groups(self, account_id: str, groups: list[dict[str, Any]]) -> dict[str, Any]:
        """把连接器返回的群登记为白名单候选；默认不启用 AI 回复。"""
        created = 0
        updated = 0
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在。", status_code=400)
            for item in groups[:500]:
                platform_id = _clean(item.get("platform_group_id") or item.get("group_id"), 128)
                if not platform_id:
                    continue
                name = _clean(item.get("name") or item.get("group_name"), _MAX_NAME) or None
                existing = await session.scalar(
                    select(Group).where(
                        Group.account_id == account_id,
                        Group.platform_group_id == platform_id,
                    )
                )
                if existing is None:
                    session.add(
                        Group(
                            account_id=account_id,
                            platform_group_id=platform_id,
                            name=name,
                            enabled=False,
                            reply_mode="observe",
                            timezone=self.settings.default_timezone,
                        )
                    )
                    created += 1
                elif name and existing.name != name:
                    existing.name = name
                    updated += 1
            await session.commit()
        if created or updated:
            await write_audit(
                self.database,
                action="group.import",
                target_type="account",
                target_id=account_id,
                details={"created": created, "updated": updated},
            )
        return {"created": created, "updated": updated}

    async def list_members(self, account_id: str | None = None) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            query = select(Member).order_by(Member.platform_user_id)
            if account_id:
                query = query.where(Member.account_id == account_id)
            members = list((await session.execute(query)).scalars())
        now = utcnow()
        return [
            {
                "id": member.id,
                "account_id": member.account_id,
                "platform_user_id": member.platform_user_id,
                "display_name": member.display_name,
                "labels": list(member.labels_json or []),
                "excluded_from_memory": member.excluded_from_memory,
                "muted": bool(member.muted_until and member.muted_until > now),
                "muted_until": iso_utc(member.muted_until),
                "created_at": iso_utc(member.created_at),
            }
            for member in members
        ]
