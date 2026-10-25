"""进程内事件总线：用于 SSE 推送与仪表盘最近事件。慢客户端不阻塞流水线。"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.security import redact_value
from app.core.time import iso_utc, utcnow

_SUBSCRIBER_QUEUE_SIZE = 200
_RECENT_EVENT_LIMIT = 100


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._recent: deque[dict[str, Any]] = deque(maxlen=_RECENT_EVENT_LIMIT)
        self._sequence = 0

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self._sequence += 1
        event = {
            "seq": self._sequence,
            "type": event_type,
            "at": iso_utc(utcnow()),
            "payload": redact_value(payload or {}),
        }
        self._recent.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    continue
        return event

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return list(self._recent)[-limit:][::-1]

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
