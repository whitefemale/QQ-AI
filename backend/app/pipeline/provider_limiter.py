"""单进程内的 LLM Provider 并发与最小间隔保护。

这不是分布式限流，也不能替代服务商侧的配额；重启后状态清零。
Mock 只在本地执行，不占用真实 Provider 配额，因此跳过限流。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager


class ProviderLimiter:
    def __init__(
        self,
        *,
        max_concurrency: int = 2,
        min_interval_ms: int = 200,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.max_concurrency = max(1, int(max_concurrency))
        self.min_interval_seconds = max(0.0, float(min_interval_ms) / 1000.0)
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._gates: dict[str, asyncio.Lock] = {}
        self._last_started: dict[str, float] = {}

    @asynccontextmanager
    async def slot(self, provider_id: str, *, is_mock: bool = False) -> AsyncIterator[None]:
        if is_mock:
            yield
            return
        semaphore = self._semaphores.setdefault(provider_id, asyncio.Semaphore(self.max_concurrency))
        gate = self._gates.setdefault(provider_id, asyncio.Lock())
        async with semaphore:
            async with gate:
                last = self._last_started.get(provider_id)
                if last is not None and self.min_interval_seconds > 0:
                    delay = self.min_interval_seconds - (self._clock() - last)
                    if delay > 0:
                        await self._sleep(delay)
                self._last_started[provider_id] = self._clock()
            yield
