"""演示环境初始化（完全使用 Mock，不接触真实 QQ）。"""

from __future__ import annotations

from typing import Any

from app.api.deps import get_actor, get_runtime
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.runtime import AppRuntime
from app.services.audit import write_audit
from fastapi import APIRouter, Depends, Request

router = APIRouter()


@router.post("/demo/bootstrap")
async def bootstrap_demo(
    request: Request,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    result = await runtime.demo.bootstrap()
    await write_audit(
        runtime.database,
        action="demo.bootstrap.request",
        target_type="system",
        details={"created": result.get("created")},
        actor=get_actor(request),
    )
    return ok(result)


@router.post("/demo/reset-hint")
async def demo_reset_hint() -> dict[str, Any]:
    raise AppError(
        ErrorCode.OPERATION_PLANNED,
        "一键清空演示数据尚未实现。请在对应页面逐项删除演示账号、群与人格。",
        status_code=501,
    )
