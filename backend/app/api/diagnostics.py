"""只读诊断摘要接口；不提供日志下载或主动检查。"""

from __future__ import annotations

from typing import Any

from app.api.deps import get_runtime
from app.core.response import ok
from app.runtime import AppRuntime
from fastapi import APIRouter, Depends

router = APIRouter()


@router.get("/diagnostics")
async def diagnostics(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.diagnostics.build())
