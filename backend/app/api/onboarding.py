"""只读接入向导接口。"""

from __future__ import annotations

from typing import Any

from app.api.deps import get_runtime
from app.core.response import ok
from app.runtime import AppRuntime
from fastapi import APIRouter, Depends

router = APIRouter()


@router.get("/onboarding")
async def onboarding(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.onboarding.build())
