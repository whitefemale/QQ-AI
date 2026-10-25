"""模拟测试：dry-run 不发送、不落库；Mock 事件注入只走 Mock 适配器。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.adapters.qq.mock import MockQQAdapter
from app.core.errors import AppError, ErrorCode
from app.core.time import utcnow
from app.db.session import Database
from app.models.account import Account
from app.models.group import Group
from app.models.persona import Persona
from app.pipeline.orchestrator import MessagePipeline
from app.schemas.message import CanonicalMessage, MessageSegment
from app.services.adapter_manager import AdapterManager


class PlaygroundService:
    def __init__(
        self,
        database: Database,
        pipeline: MessagePipeline,
        manager: AdapterManager,
    ) -> None:
        self.database = database
        self.pipeline = pipeline
        self.manager = manager

    async def run_dry(self, payload: dict[str, Any]) -> dict[str, Any]:
        account_id = str(payload.get("account_id") or "").strip()
        if not account_id:
            raise AppError(ErrorCode.VALIDATION_ERROR, "请选择用于模拟的账号。", status_code=400)
        conversation_type = str(payload.get("conversation_type") or "group")
        if conversation_type not in {"group", "private"}:
            raise AppError(ErrorCode.VALIDATION_ERROR, "会话类型无效。", status_code=400)
        text = str(payload.get("text") or "")[:4000]
        raw_segments = payload.get("segments")
        segments = self._parse_segments(raw_segments, text)
        if not any(segment.type not in {"text", "reply"} for segment in segments) and not text.strip():
            raise AppError(ErrorCode.VALIDATION_ERROR, "请输入模拟消息内容。", status_code=400)
        persona_id_override = str(payload.get("persona_id") or "").strip() or None
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在。", status_code=404)
            group: Group | None = None
            if conversation_type == "group":
                group_id = str(payload.get("group_id") or "").strip()
                if not group_id:
                    raise AppError(ErrorCode.VALIDATION_ERROR, "群聊模拟请选择已登记的群。", status_code=400)
                group = await session.scalar(select(Group).where(Group.id == group_id, Group.account_id == account_id))
                if group is None:
                    raise AppError(ErrorCode.NOT_FOUND, "群不存在或不属于该账号。", status_code=404)
            if persona_id_override is not None:
                if await session.get(Persona, persona_id_override) is None:
                    raise AppError(ErrorCode.PERSONA_NOT_FOUND, "人格不存在。", status_code=404)
        adapter = MockQQAdapter(
            instance_id="playground",
            account_id=account.id,
            self_id=account.self_platform_user_id or "10000",
        )
        sender_id = str(payload.get("sender_id") or "20001")[:128]
        raw_mentions: Any = payload.get("mentions")
        mentions: list[Any] = raw_mentions if isinstance(raw_mentions, list) else []
        message = CanonicalMessage(
            platform="qq",
            account_id=account.id,
            message_id=f"playground-{uuid.uuid4().hex[:16]}",
            conversation_id=group.platform_group_id if group else "playground-private",
            conversation_type=conversation_type,  # type: ignore[arg-type]
            sender_id=sender_id,
            sender_name=str(payload.get("sender_name") or "模拟群友")[:64],
            segments=segments,
            mentions=[str(item)[:64] for item in mentions[:20]],
            reply_to_message_id=str(payload.get("reply_to_message_id") or "")[:128] or None,
            timestamp=utcnow(),
            is_self_message=False,
            source_adapter="playground",
            event_id=f"playground-{uuid.uuid4().hex}",
        )
        result = await self.pipeline.handle(
            message,
            account=account,
            group=group,
            adapter=adapter,
            dry_run=True,
            persona_id_override=persona_id_override,
        )
        return {
            "dry_run": True,
            "sent": False,
            "persisted": False,
            "note": "模拟运行不会发送到 QQ，也不会写入消息日志。",
            "result": result.as_dict(),
        }

    @staticmethod
    def _parse_segments(raw: Any, text: str) -> list[MessageSegment]:
        if not isinstance(raw, list) or not raw:
            return [MessageSegment(type="text", text=text)] if text else []
        segments: list[MessageSegment] = []
        for item in raw[:20]:
            if not isinstance(item, dict):
                continue
            try:
                segments.append(MessageSegment.model_validate(item))
            except Exception as exc:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "消息段格式无效。",
                    status_code=400,
                ) from exc
        return segments

    async def inject_mock_event(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """把事件注入 Mock 适配器，走完整持久化/发送流程；真实 QQ 账号不可用此接口。"""
        async with self.database.session() as session:
            account = await session.get(Account, account_id)
            if account is None:
                raise AppError(ErrorCode.NOT_FOUND, "账号不存在。", status_code=404)
            group: Group | None = None
            if payload.get("group_internal_id"):
                group = await session.get(Group, str(payload["group_internal_id"]))
                if group is None or group.account_id != account_id:
                    raise AppError(ErrorCode.NOT_FOUND, "群不存在或不属于该账号。", status_code=404)
            elif payload.get("group_platform_id"):
                group = await session.scalar(
                    select(Group).where(
                        Group.account_id == account_id,
                        Group.platform_group_id == str(payload["group_platform_id"]),
                    )
                )
        adapter = self._mock_adapter(account)
        if adapter is None:
            raise AppError(
                ErrorCode.ADAPTER_UNSUPPORTED_OPERATION,
                "该账号没有启用中的 Mock 连接器，不能注入模拟事件。真实 QQ 账号绝不会接收模拟事件。",
                status_code=400,
            )
        text = str(payload.get("text") or "")[:4000]
        segments = self._parse_segments(payload.get("segments"), text)
        if not segments:
            raise AppError(ErrorCode.VALIDATION_ERROR, "模拟消息不能为空。", status_code=400)
        message = adapter.inject_message(
            conversation_id=group.platform_group_id if group else "100001",
            conversation_type="group",
            sender_id=str(payload.get("sender_id") or "20001")[:128],
            sender_name=str(payload.get("sender_name") or "测试群友")[:64],
            text=text,
            segments=segments,
            mentions=[str(item)[:64] for item in payload.get("mentions", [])]
            if isinstance(payload.get("mentions"), list)
            else [],
            reply_to_message_id=str(payload.get("reply_to_message_id") or "")[:128] or None,
        )
        sent_before = len(adapter.sent_messages)
        result = await self.manager.handle_event(adapter, message)
        newly_sent = adapter.sent_messages[sent_before:]
        sent_text = newly_sent[-1].raw.get("text") if newly_sent else None
        return {
            "dry_run": False,
            "sent": bool(newly_sent),
            "persisted": True,
            "mock": True,
            "sent_text": sent_text,
            "result": result,
        }

    def _mock_adapter(self, account: Account) -> MockQQAdapter | None:
        for instance in account.instances:
            if instance.connection_mode != "mock" or not instance.enabled:
                continue
            adapter = self.manager.get_adapter(instance.id)
            if isinstance(adapter, MockQQAdapter) and adapter.status == "online":
                return adapter
        return None
