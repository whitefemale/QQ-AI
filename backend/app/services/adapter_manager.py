"""QQ 适配器运行时：创建、连接、监督、事件分发与发送队列后台重试。

约束：
- 适配器实例的配置来自数据库；Token 只在需要时解密进内存。
- 一个账号的多条事件串行处理，避免上下文和限速状态竞争。
- 全局紧急暂停期间后台不发送任何排队消息。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.adapters.qq.base import BaseQQAdapter
from app.adapters.qq.mock import MockQQAdapter
from app.adapters.qq.onebot11 import OneBot11Adapter
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import CredentialCipher
from app.core.time import utcnow
from app.db.session import Database
from app.models.account import Account, AdapterInstance
from app.models.group import Group
from app.models.persona import Persona
from app.pipeline.events import EventBus
from app.pipeline.orchestrator import MessagePipeline
from app.pipeline.outbox import OutboxService
from app.pipeline.persona_growth import PersonaGrowthService
from app.schemas.message import CanonicalMessage
from app.services.settings_store import get_global_pause

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_SECONDS = 20.0


class AdapterManager:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        cipher: CredentialCipher,
        pipeline: MessagePipeline,
        outbox: OutboxService,
        events: EventBus,
        growth: PersonaGrowthService | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.cipher = cipher
        self.pipeline = pipeline
        self.outbox = outbox
        self.events = events
        self.growth = growth
        self._adapters: dict[str, BaseQQAdapter] = {}
        self._listeners: dict[str, asyncio.Task[None]] = {}
        self._instance_locks: dict[str, asyncio.Lock] = {}
        self._account_locks: dict[str, asyncio.Lock] = {}
        self._growth_tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    # ------------------------------------------------------------------ 构建
    def _instance_lock(self, instance_id: str) -> asyncio.Lock:
        return self._instance_locks.setdefault(instance_id, asyncio.Lock())

    def _account_lock(self, account_id: str) -> asyncio.Lock:
        return self._account_locks.setdefault(account_id, asyncio.Lock())

    def build_adapter(self, instance: AdapterInstance, account: Account) -> BaseQQAdapter:
        mode = instance.connection_mode or "mock"
        token: str | None = None
        if instance.token_encrypted:
            token = self.cipher.decrypt(instance.token_encrypted)
        if mode == "mock":
            return MockQQAdapter(
                instance_id=instance.id,
                account_id=account.id,
                endpoint=instance.endpoint,
                self_id=account.self_platform_user_id or "10000",
            )
        if mode == "onebot11":
            if not instance.endpoint:
                raise AppError(
                    ErrorCode.ADAPTER_CONNECT_FAILED,
                    "请填写 OneBot 11 WebSocket 地址（例如 ws://127.0.0.1:3001）。",
                    status_code=400,
                )
            return OneBot11Adapter(
                instance_id=instance.id,
                account_id=account.id,
                endpoint=instance.endpoint,
                api_endpoint=instance.api_endpoint,
                token=token,
                allow_remote=instance.allow_remote,
            )
        if mode in {"official", "official_bot"}:
            raise AppError(
                ErrorCode.OPERATION_PLANNED,
                "官方 QQ 机器人接入尚未实现，当前版本仅预留接口。",
                status_code=501,
            )
        raise AppError(
            ErrorCode.ADAPTER_CONNECT_FAILED,
            f"未知的连接方式「{mode}」。",
            status_code=400,
        )

    async def _load_pair(self, instance_id: str) -> tuple[AdapterInstance, Account]:
        async with self.database.session() as session:
            instance = await session.get(AdapterInstance, instance_id)
            if instance is None:
                raise AppError(ErrorCode.ADAPTER_NOT_FOUND, "连接器实例不存在。", status_code=404)
            account = await session.get(Account, instance.account_id)
            if account is None:
                raise AppError(ErrorCode.ADAPTER_NOT_FOUND, "账号不存在。", status_code=404)
            return instance, account

    def _status_callback(self, instance_id: str, account_id: str):
        async def callback(status: str, error_code: str | None, error_message: str | None) -> None:
            await self._persist_status(instance_id, account_id, status, error_code, error_message)

        return callback

    async def _persist_status(
        self,
        instance_id: str,
        account_id: str,
        status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        adapter = self._adapters.get(instance_id)
        try:
            async with self.database.session() as session:
                instance = await session.get(AdapterInstance, instance_id)
                if instance is None:
                    return
                previous_status = instance.status
                instance.status = status
                instance.last_error_code = error_code
                instance.last_error_message = error_message
                if adapter is not None:
                    instance.last_heartbeat_at = adapter.last_heartbeat_at
                    instance.last_received_at = adapter.last_received_at
                    instance.last_sent_at = adapter.last_sent_at
                    if status == "online":
                        instance.capabilities_json = adapter.capabilities().as_dict()
                account = await session.get(Account, instance.account_id)
                if account is None:
                    await session.commit()
                    return
                if adapter is not None and adapter.self_platform_user_id:
                    account.self_platform_user_id = adapter.self_platform_user_id
                online_siblings = [
                    item for item in account.instances if item.id != instance_id and item.status == "online"
                ]
                if status == "online" or online_siblings:
                    account.status = "online"
                else:
                    account.status = status
                await session.commit()
        except Exception:
            logger.exception("持久化适配器状态失败", extra={"adapter_instance_id": instance_id})
            return
        if previous_status != status or error_code is not None:
            self.events.publish(
                "adapter.status",
                {
                    "instance_id": instance_id,
                    "account_id": account_id,
                    "status": status,
                    "error_code": error_code,
                    "message": error_message,
                },
            )

    # ------------------------------------------------------------------ 连接
    async def connect_instance(self, instance_id: str) -> BaseQQAdapter:
        async with self._instance_lock(instance_id):
            cached = self._adapters.get(instance_id)
            if cached is not None:
                if self._is_online(cached):
                    return cached
                if isinstance(cached, OneBot11Adapter) and cached.status == "reconnecting":
                    # 后台监督任务正在指数退避重连，避免重复建立连接。
                    return cached
            instance, account = await self._load_pair(instance_id)
            if not account.enabled:
                raise AppError(ErrorCode.ADAPTER_UNAVAILABLE, "账号已停用，不能连接。", status_code=400)
            if not instance.enabled:
                raise AppError(ErrorCode.ADAPTER_UNAVAILABLE, "连接器实例已停用，不能连接。", status_code=400)
            if cached is not None:
                await self._teardown(instance_id, disconnect=True)
            adapter = self.build_adapter(instance, account)
            adapter.set_status_callback(self._status_callback(instance.id, account.id))
            self._adapters[instance_id] = adapter
            try:
                await asyncio.wait_for(adapter.connect(), timeout=_CONNECT_TIMEOUT_SECONDS)
            except TimeoutError as exc:
                await self._teardown(instance_id, disconnect=True)
                await self._persist_status(
                    instance_id,
                    account.id,
                    "error",
                    ErrorCode.ADAPTER_CONNECT_FAILED,
                    "连接超时，请检查连接器是否已启动。",
                )
                raise AppError(
                    ErrorCode.ADAPTER_CONNECT_FAILED,
                    "连接连接器超时，请检查地址与连接器状态。",
                    status_code=504,
                ) from exc
            except AppError:
                await self._teardown(instance_id, disconnect=True)
                raise
            except Exception as exc:
                await self._teardown(instance_id, disconnect=True)
                logger.exception("连接连接器失败")
                raise AppError(
                    ErrorCode.ADAPTER_CONNECT_FAILED,
                    "连接连接器时发生异常。",
                    status_code=500,
                    details={"reason": type(exc).__name__},
                ) from exc
            self._start_listener(adapter)
            await self._persist_status(instance_id, account.id, adapter.status, None, None)
            return adapter

    async def disconnect_instance(self, instance_id: str) -> None:
        async with self._instance_lock(instance_id):
            await self._teardown(instance_id, disconnect=True)

    async def disconnect_account(self, account_id: str) -> None:
        for instance_id, adapter in list(self._adapters.items()):
            if adapter.account_id != account_id:
                continue
            async with self._instance_lock(instance_id):
                await self._teardown(instance_id, disconnect=True)

    async def _teardown(self, instance_id: str, *, disconnect: bool) -> None:
        listener = self._listeners.pop(instance_id, None)
        if listener is not None:
            listener.cancel()
            try:
                await listener
            except (asyncio.CancelledError, Exception):
                pass
        adapter = self._adapters.pop(instance_id, None)
        if adapter is not None and disconnect:
            try:
                await adapter.disconnect()
            except Exception:
                logger.exception("断开适配器失败", extra={"adapter_instance_id": instance_id})
            try:
                instance, account = await self._load_pair(instance_id)
            except AppError:
                return
            await self._persist_status(instance_id, account.id, "disconnected", None, None)

    async def forget_instance(self, instance_id: str) -> None:
        """配置变更或删除实例时丢弃缓存，避免使用旧 Token/地址。"""
        async with self._instance_lock(instance_id):
            await self._teardown(instance_id, disconnect=True)

    def _start_listener(self, adapter: BaseQQAdapter) -> None:
        old = self._listeners.pop(adapter.instance_id, None)
        if old is not None:
            old.cancel()
        self._listeners[adapter.instance_id] = asyncio.create_task(
            self._listen(adapter), name=f"qq-events-{adapter.instance_id}"
        )

    async def _listen(self, adapter: BaseQQAdapter) -> None:
        while not self._closed and self._adapters.get(adapter.instance_id) is adapter:
            try:
                message = await adapter.next_event()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("读取适配器事件失败", extra={"adapter_instance_id": adapter.instance_id})
                await asyncio.sleep(1)
                continue
            try:
                await self.handle_event(adapter, message)
            except Exception:
                logger.exception("处理适配器事件失败", extra={"adapter_instance_id": adapter.instance_id})

    async def handle_event(self, adapter: BaseQQAdapter, message: CanonicalMessage) -> dict[str, Any]:
        async with self.database.session() as session:
            account = await session.get(Account, message.account_id)
            if account is None or not account.enabled:
                return {"accepted": False, "action": "intercept", "reason": "account_unavailable"}
            group: Group | None = None
            if message.conversation_type == "group":
                group = await session.scalar(
                    select(Group).where(
                        Group.account_id == account.id,
                        Group.platform_group_id == message.conversation_id,
                    )
                )
        async with self._account_lock(account.id):
            result = await self.pipeline.handle(
                message,
                account=account,
                group=group,
                adapter=adapter,
            )
        if result.action in {"replied", "command"} and group is not None:
            self._schedule_growth(group)
        return result.as_dict()

    def _schedule_growth(self, group: Group) -> None:
        """回复成功后，为开启了自成长的空白人格安排一次后台分析。"""
        if self.growth is None or not group.persona_id:
            return
        persona_id = group.persona_id
        task = asyncio.create_task(
            self._maybe_grow(persona_id, group.id),
            name=f"persona-growth-{persona_id[:8]}",
        )
        self._growth_tasks.add(task)
        task.add_done_callback(self._growth_tasks.discard)

    async def _maybe_grow(self, persona_id: str, group_id: str) -> None:
        if self.growth is None:
            return
        try:
            async with self.database.session() as session:
                persona = await session.get(Persona, persona_id)
                if (
                    persona is None
                    or not persona.enabled
                    or persona.mode != "emergent"
                    or not persona.growth_enabled
                    or persona.growth_policy == "paused"
                ):
                    return
            await self.growth.analyze(
                persona_id,
                group_id=group_id,
                trigger="auto",
                actor="system",
            )
        except AppError as exc:
            logger.info(
                "自动人格成长未执行",
                extra={"error_code": exc.code, "persona_id": persona_id},
            )
        except Exception:
            logger.exception("自动人格成长失败", extra={"persona_id": persona_id})

    # ------------------------------------------------------------------ 查询
    def get_adapter(self, instance_id: str) -> BaseQQAdapter | None:
        return self._adapters.get(instance_id)

    def online_adapter(self, account_id: str, instance_id: str | None = None) -> BaseQQAdapter | None:
        if instance_id:
            adapter = self._adapters.get(instance_id)
            if adapter is not None and self._is_online(adapter) and adapter.account_id == account_id:
                return adapter
            return None
        for adapter in self._adapters.values():
            if adapter.account_id == account_id and self._is_online(adapter):
                return adapter
        return None

    @staticmethod
    def _is_online(adapter: BaseQQAdapter) -> bool:
        if isinstance(adapter, OneBot11Adapter):
            return adapter.online
        return adapter.status == "online"

    def resolve(self, account_id: str, instance_id: str | None) -> BaseQQAdapter | None:
        return self.online_adapter(account_id, instance_id)

    async def public_health(self, instance_id: str) -> dict[str, Any] | None:
        adapter = self._adapters.get(instance_id)
        if adapter is None:
            return None
        return await adapter.health_check()

    async def test_connection(
        self,
        *,
        connection_mode: str,
        endpoint: str | None,
        api_endpoint: str | None,
        token: str | None,
        allow_remote: bool,
    ) -> dict[str, Any]:
        """测试未保存的配置；连接后立即断开，不发送任何消息。"""
        adapter = self._build_ephemeral(
            connection_mode=connection_mode,
            endpoint=endpoint,
            api_endpoint=api_endpoint,
            token=token,
            allow_remote=allow_remote,
        )
        started = utcnow()
        try:
            await asyncio.wait_for(adapter.connect(), timeout=_CONNECT_TIMEOUT_SECONDS)
            login = await adapter.get_login_info()
            groups = await adapter.get_group_list()
        finally:
            try:
                await adapter.disconnect()
            except Exception:
                pass
        return {
            "ok": True,
            "connection_mode": connection_mode,
            "login": login,
            "groups": groups[:50],
            "group_count": len(groups),
            "tested_at": started.isoformat(),
            "latency_ms": int((utcnow() - started).total_seconds() * 1000),
        }

    def _build_ephemeral(
        self,
        *,
        connection_mode: str,
        endpoint: str | None,
        api_endpoint: str | None,
        token: str | None,
        allow_remote: bool,
    ) -> BaseQQAdapter:
        if connection_mode == "mock":
            return MockQQAdapter(instance_id="test-instance", account_id="test-account")
        if connection_mode == "onebot11":
            if not endpoint:
                raise AppError(
                    ErrorCode.ADAPTER_CONNECT_FAILED,
                    "请填写 OneBot 11 WebSocket 地址。",
                    status_code=400,
                )
            return OneBot11Adapter(
                instance_id="test-instance",
                account_id="test-account",
                endpoint=endpoint,
                api_endpoint=api_endpoint,
                token=token,
                allow_remote=allow_remote,
            )
        raise AppError(
            ErrorCode.ADAPTER_CONNECT_FAILED,
            "未知的连接方式。",
            status_code=400,
        )

    # ------------------------------------------------------------------ 生命周期
    async def start(self) -> None:
        self._closed = False
        async with self.database.session() as session:
            instances = list(
                (
                    await session.execute(
                        select(AdapterInstance)
                        .join(Account, Account.id == AdapterInstance.account_id)
                        .where(
                            AdapterInstance.enabled.is_(True),
                            AdapterInstance.auto_connect.is_(True),
                            Account.enabled.is_(True),
                        )
                    )
                ).scalars()
            )
        if not instances:
            return

        async def _connect(instance_id: str) -> None:
            try:
                await self.connect_instance(instance_id)
            except AppError as exc:
                logger.warning(
                    "自动连接失败",
                    extra={"adapter_instance_id": instance_id, "error_code": exc.code},
                )
            except Exception:
                logger.exception("自动连接异常", extra={"adapter_instance_id": instance_id})

        await asyncio.gather(*(_connect(instance.id) for instance in instances))

    async def stop(self) -> None:
        self._closed = True
        for task in list(self._growth_tasks):
            task.cancel()
        if self._growth_tasks:
            await asyncio.gather(*self._growth_tasks, return_exceptions=True)
        self._growth_tasks.clear()
        for instance_id in list(self._adapters):
            await self._teardown(instance_id, disconnect=True)
        self._listeners.clear()
        self._adapters.clear()


class OutboxWorker:
    """后台重试发送队列；全局暂停时完全不发送。"""

    def __init__(
        self,
        manager: AdapterManager,
        database: Database,
        outbox: OutboxService,
        *,
        interval: float = 2.0,
    ) -> None:
        self.manager = manager
        self.database = database
        self.outbox = outbox
        self.interval = interval
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="outbox-retry-worker")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        while True:
            try:
                pause = await get_global_pause(self.database)
                if not pause.get("paused"):
                    await self.outbox.send_due(self.manager.resolve)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("后台发送队列处理失败")
            await asyncio.sleep(self.interval)


def heartbeat_age_seconds(value: datetime | None) -> float | None:
    if value is None:
        return None
    return max(0.0, (utcnow() - value).total_seconds())


__all__ = ["AdapterManager", "OutboxWorker", "heartbeat_age_seconds"]
