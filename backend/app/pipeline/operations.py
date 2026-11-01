"""显式模型测试的本地操作注册表。

只登记内部模型调用任务；取消端点只能取消本进程内仍在等待的任务。
它不代表服务商停止生成或停止计费。进程重启后注册表清空。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from app.core.errors import AppError, ErrorCode

_OPERATION_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def validate_operation_id(operation_id: str) -> str:
    if not _OPERATION_ID.fullmatch(operation_id):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "operation_id 必须为 8–64 位字母、数字、下划线或短横线。",
            status_code=400,
        )
    return operation_id


class ProviderOperationRegistry:
    def __init__(self) -> None:
        self._tasks: dict[tuple[str, str], asyncio.Task[Any]] = {}

    def begin(self, provider_id: str, operation_id: str, task: asyncio.Task[Any]) -> None:
        validate_operation_id(operation_id)
        key = (provider_id, operation_id)
        current = self._tasks.get(key)
        if current is not None and not current.done():
            raise AppError(
                ErrorCode.PROVIDER_OPERATION_CONFLICT,
                "同一 operation_id 已有进行中的模型测试，请等待完成或先取消。",
                status_code=409,
            )
        self._tasks[key] = task

    def finish(self, provider_id: str, operation_id: str, task: asyncio.Task[Any]) -> None:
        key = (provider_id, operation_id)
        if self._tasks.get(key) is task:
            self._tasks.pop(key, None)

    def cancel(self, provider_id: str, operation_id: str) -> bool:
        validate_operation_id(operation_id)
        task = self._tasks.get((provider_id, operation_id))
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def active_count(self) -> int:
        return sum(1 for task in self._tasks.values() if not task.done())
