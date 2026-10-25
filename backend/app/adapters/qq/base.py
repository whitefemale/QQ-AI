"""QQ 适配器抽象。平台专有能力由具体适配器声明，业务层不得假设。"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from app.core.errors import AppError, ErrorCode
from app.core.time import iso_utc, utcnow
from app.schemas.message import CanonicalMessage, SentMessage

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str, str | None, str | None], Awaitable[None] | None]


@dataclass
class AdapterCapabilities:
    receive_group_message: bool = False
    receive_private_message: bool = False
    send_text: bool = False
    send_image: bool = False
    send_reply: bool = False
    mention_support: bool = False
    group_member_info: bool = False
    group_list: bool = False
    message_recall_event: bool = False
    file_upload: bool = False
    voice_message: bool = False
    video_message: bool = False
    typing_indicator: bool = False
    official_api: bool = False

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


class BaseQQAdapter(ABC):
    adapter_type: str = "base"

    def __init__(
        self,
        *,
        instance_id: str,
        account_id: str,
        endpoint: str | None = None,
        token: str | None = None,
        allow_remote: bool = False,
    ) -> None:
        self.instance_id = instance_id
        self.account_id = account_id
        self.endpoint = endpoint
        self.token = token
        self.allow_remote = allow_remote
        self.status = "disconnected"
        self.self_platform_user_id: str | None = None
        self.last_heartbeat_at: datetime | None = None
        self.last_received_at: datetime | None = None
        self.last_sent_at: datetime | None = None
        self.last_error_code: str | None = None
        self.last_error_message: str | None = None
        self._queue: asyncio.Queue[CanonicalMessage] = asyncio.Queue(maxsize=1000)
        self._status_callback: StatusCallback | None = None

    def set_status_callback(self, callback: StatusCallback | None) -> None:
        self._status_callback = callback

    async def _notify_status(self) -> None:
        if self._status_callback is None:
            return
        result = self._status_callback(self.status, self.last_error_code, self.last_error_message)
        if asyncio.iscoroutine(result):
            await result

    async def _set_status(self, status: str, error_code: str | None = None, error_message: str | None = None) -> None:
        self.status = status
        self.last_error_code = error_code
        self.last_error_message = error_message
        await self._notify_status()

    @abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        raise NotImplementedError

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send_text(
        self,
        conversation_id: str,
        text: str,
        *,
        conversation_type: str = "group",
        reply_to_message_id: str | None = None,
    ) -> SentMessage:
        raise NotImplementedError

    async def health_check(self) -> dict[str, Any]:
        return {
            "ok": self.status == "online",
            "status": self.status,
            "adapter_type": self.adapter_type,
            "instance_id": self.instance_id,
            "last_heartbeat_at": iso_utc(self.last_heartbeat_at),
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
        }

    async def get_group_list(self) -> list[dict[str, Any]]:
        raise AppError(
            ErrorCode.ADAPTER_UNSUPPORTED_OPERATION,
            "当前连接器不支持获取群列表。",
            status_code=400,
        )

    async def get_login_info(self) -> dict[str, Any] | None:
        return None

    async def next_event(self) -> CanonicalMessage:
        return await self._queue.get()

    def queue_event(self, message: CanonicalMessage) -> None:
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(
                "适配器事件队列已满，丢弃最旧事件",
                extra={"adapter_instance_id": self.instance_id},
            )
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(message)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    def touch_received(self) -> None:
        self.last_received_at = utcnow()

    def touch_sent(self) -> None:
        self.last_sent_at = utcnow()

    def ensure_endpoint_allowed(self) -> None:
        """公网连接器默认拒绝，避免误将管理端暴露到不可信网络。"""
        if not self.endpoint:
            return
        parsed = urlparse(self.endpoint)
        host = parsed.hostname
        if not host:
            raise AppError(ErrorCode.ADAPTER_CONNECT_FAILED, "连接器地址无效。", status_code=400)
        if host in {"localhost", "127.0.0.1", "::1"}:
            return
        try:
            address = ipaddress.ip_address(host)
            if address.is_loopback or address.is_private:
                return
        except ValueError:
            pass
        if not self.allow_remote:
            raise AppError(
                ErrorCode.ADAPTER_REMOTE_FORBIDDEN,
                "连接器地址不是本机或私网地址。若确需公网连接，请显式开启「允许远程连接」并自行承担风险。",
                status_code=400,
            )
