"""Mock QQ 适配器：用于开发、演示和自动化测试，不登录真实 QQ。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from app.adapters.qq.base import AdapterCapabilities, BaseQQAdapter
from app.core.errors import AppError, ErrorCode
from app.core.time import utcnow
from app.schemas.message import CanonicalMessage, MessageSegment, SentMessage


class MockQQAdapter(BaseQQAdapter):
    adapter_type = "mock"

    def __init__(
        self,
        *,
        instance_id: str,
        account_id: str,
        endpoint: str | None = None,
        token: str | None = None,
        allow_remote: bool = False,
        self_id: str = "10000",
    ) -> None:
        super().__init__(
            instance_id=instance_id,
            account_id=account_id,
            endpoint=endpoint,
            token=token,
            allow_remote=allow_remote,
        )
        self.self_platform_user_id = self_id
        self.sent_messages: list[SentMessage] = []
        self.failure_mode: str | None = None
        self.demo_groups = [
            {"group_id": "100001", "group_name": "Mock 演示群"},
            {"group_id": "100002", "group_name": "Mock 测试群"},
        ]

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            receive_group_message=True,
            receive_private_message=True,
            send_text=True,
            send_image=False,
            send_reply=True,
            mention_support=True,
            group_member_info=False,
            group_list=True,
            message_recall_event=False,
            file_upload=False,
            voice_message=False,
            video_message=False,
            typing_indicator=False,
            official_api=False,
        )

    async def connect(self) -> None:
        await asyncio.sleep(0)
        self.last_heartbeat_at = utcnow()
        await self._set_status("online")

    async def disconnect(self) -> None:
        await self._set_status("disconnected")

    async def health_check(self) -> dict[str, Any]:
        result = await super().health_check()
        result["mode"] = "mock"
        return result

    async def get_group_list(self) -> list[dict[str, Any]]:
        return list(self.demo_groups)

    async def get_login_info(self) -> dict[str, Any] | None:
        return {"user_id": self.self_platform_user_id, "nickname": "Mock AI 群友"}

    async def send_text(
        self,
        conversation_id: str,
        text: str,
        *,
        conversation_type: str = "group",
        reply_to_message_id: str | None = None,
    ) -> SentMessage:
        if self.failure_mode == "timeout":
            raise AppError(
                ErrorCode.SEND_STATUS_UNKNOWN,
                "Mock 模拟发送超时：发送状态未知。",
                status_code=504,
                retryable=False,
            )
        if self.failure_mode == "transient":
            raise AppError(ErrorCode.SEND_FAILED, "Mock 模拟可重试发送失败。", status_code=503, retryable=True)
        if self.failure_mode == "permanent":
            raise AppError(ErrorCode.SEND_FAILED, "Mock 模拟永久发送失败。", status_code=400)
        sent = SentMessage(
            platform_message_id=f"mock-out-{uuid.uuid4().hex[:12]}",
            conversation_id=conversation_id,
            status="sent",
            raw={
                "conversation_type": conversation_type,
                "reply_to_message_id": reply_to_message_id,
                "text": text,
                "mock": True,
            },
        )
        self.sent_messages.append(sent)
        self.last_sent_at = utcnow()
        return sent

    def inject_message(
        self,
        *,
        conversation_id: str = "100001",
        conversation_type: str = "group",
        sender_id: str = "20001",
        sender_name: str | None = "测试群友",
        text: str = "",
        segments: list[MessageSegment] | None = None,
        mentions: list[str] | None = None,
        reply_to_message_id: str | None = None,
        message_id: str | None = None,
        timestamp: datetime | None = None,
        is_self_message: bool = False,
    ) -> CanonicalMessage:
        if segments is None:
            segments = [MessageSegment(type="text", text=text)]
        message = CanonicalMessage(
            platform="qq",
            account_id=self.account_id,
            message_id=message_id or f"mock-in-{uuid.uuid4().hex[:12]}",
            conversation_id=conversation_id,
            conversation_type=conversation_type,  # type: ignore[arg-type]
            sender_id=sender_id,
            sender_name=sender_name,
            segments=segments,
            mentions=mentions or [],
            reply_to_message_id=reply_to_message_id,
            timestamp=timestamp or utcnow(),
            is_self_message=is_self_message or sender_id == self.self_platform_user_id,
            source_adapter="mock",
            event_id=f"mock-event-{uuid.uuid4().hex[:12]}",
        )
        self.touch_received()
        return message
