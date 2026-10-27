"""媒体任务后台 worker：轮询排队任务，异常隔离，不阻塞 QQ 事件接收。"""

from __future__ import annotations

import asyncio
import logging

from app.media.jobs import MediaJobService

logger = logging.getLogger(__name__)


class MediaWorker:
    def __init__(
        self,
        jobs: MediaJobService,
        *,
        interval_seconds: float = 2.0,
        batch_size: int = 10,
    ) -> None:
        self.jobs = jobs
        self.interval_seconds = max(0.5, float(interval_seconds))
        self.batch_size = max(1, int(batch_size))
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="media-worker")
        logger.info("媒体 worker 已启动", extra={"batch_size": self.batch_size})

    async def stop(self) -> None:
        task, self._task = self._task, None
        self._stop.set()
        if task is None:
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("媒体 worker 已停止")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.jobs.process_due_jobs(limit=self.batch_size)
            except asyncio.CancelledError:
                raise
            except Exception:
                # 单轮失败不能让 worker 退出；下一轮继续。
                logger.exception("媒体 worker 轮询失败")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue
