"""可选的群级后台记忆候选提取。

边界：
- 只有群显式开启长期记忆与自动提取后才会运行；
- 只做增量扫描，并以水位线避免重复分析同一批消息；
- 只生成待审核候选，绝不自动批准、写入正式记忆或注入提示词；
- 全局紧急暂停生效时完全停止；
- 消息不足、Provider 失败只记录在群配置上，不影响发送流水线。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.core.security import redact_text
from app.core.time import utcnow
from app.db.session import Database
from app.models.group import Group
from app.pipeline.events import EventBus
from app.services.audit import write_audit
from app.services.memory_extraction import MemoryExtractionService
from app.services.settings_store import get_global_pause

logger = logging.getLogger(__name__)


class MemoryAutoExtractionScheduler:
    def __init__(
        self,
        database: Database,
        extraction: MemoryExtractionService,
        events: EventBus,
        *,
        interval_seconds: float | None = None,
    ) -> None:
        self.database = database
        self.extraction = extraction
        self.events = events
        self.interval_seconds = max(
            1.0,
            float(
                interval_seconds
                if interval_seconds is not None
                else extraction.settings.memory_auto_extraction_interval_seconds
            ),
        )
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="memory-auto-extraction")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        self._stop_event.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass
            else:
                break
            try:
                await self.run_due()
            except asyncio.CancelledError:
                raise
            except Exception:  # 后台任务不能因单次异常退出
                logger.exception("后台记忆提取调度失败")

    async def run_due(self) -> int:
        """扫描所有显式开启自动提取的群；返回尝试处理的群数量。"""
        pause = await get_global_pause(self.database)
        if pause.get("paused"):
            return 0
        async with self.database.session() as session:
            group_ids = list(
                (
                    await session.execute(
                        select(Group.id).where(
                            Group.enabled.is_(True),
                            Group.paused.is_(False),
                            Group.allow_memory.is_(True),
                            Group.auto_memory_extraction.is_(True),
                        )
                    )
                ).scalars()
            )
        processed = 0
        for group_id in group_ids:
            try:
                await self.run_group(group_id)
                processed += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("后台记忆提取处理群失败", extra={"group_id": group_id})
        return processed

    async def run_group(self, group_id: str) -> None:
        async with self.database.session() as session:
            group = await session.get(Group, group_id)
            if group is None or not (
                group.enabled and not group.paused and group.allow_memory and group.auto_memory_extraction
            ):
                return
            watermark = group.memory_extraction_watermark_at
            watermark_message_id = group.memory_extraction_watermark_message_id

        try:
            outcome = await self.extraction.extract(
                group_id,
                since=watermark,
                after_message_id=watermark_message_id,
                raise_if_empty=False,
            )
        except AppError as exc:
            message = redact_text(f"{exc.code}: {exc.message}")[:500]
            await self._record_state(group_id, error=message)
            logger.warning("后台记忆提取失败", extra={"group_id": group_id, "code": exc.code})
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._record_state(group_id, error=f"{type(exc).__name__}: {redact_text(str(exc))}"[:500])
            logger.exception("后台记忆提取发生未预期错误", extra={"group_id": group_id})
            return

        if outcome is None:
            # 新消息不足 3 条：保留水位线，等后续消息累积后再次尝试。
            await self._record_state(group_id)
            return

        await self._record_state(
            group_id,
            watermark=outcome.watermark_at,
            watermark_message_id=outcome.watermark_message_id,
        )
        payload = {
            "group_id": group_id,
            "scanned_messages": outcome.scanned_messages,
            "created_count": outcome.created_count,
            "skipped": outcome.skipped,
            "provider_id": outcome.provider_id,
            "is_mock": outcome.is_mock,
        }
        self.events.publish("memory.auto_extraction", payload)
        if outcome.created_count:
            await write_audit(
                self.database,
                action="memory.extract.auto",
                target_type="group",
                target_id=group_id,
                details=payload,
                actor="memory-scheduler",
            )

    async def _record_state(
        self,
        group_id: str,
        *,
        watermark: datetime | None = None,
        watermark_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        async with self.database.session() as session:
            group = await session.get(Group, group_id)
            if group is None:
                return
            group.memory_extraction_last_run_at = utcnow()
            group.memory_extraction_last_error = error
            if watermark is not None:
                group.memory_extraction_watermark_at = watermark
                group.memory_extraction_watermark_message_id = watermark_message_id
            await session.commit()


__all__ = ["MemoryAutoExtractionScheduler"]
