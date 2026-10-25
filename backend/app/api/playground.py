"""模拟测试与演示环境。"""

from __future__ import annotations

from typing import Any

from app.api.deps import as_payload, get_runtime
from app.core.response import ok
from app.runtime import AppRuntime
from fastapi import APIRouter, Body, Depends

router = APIRouter()


@router.post("/playground/run")
async def run_playground(
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.playground.run_dry(as_payload(payload)))


@router.get("/playground/options")
async def playground_options(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    accounts = await runtime.accounts.list_accounts()
    groups = await runtime.groups.list_groups()
    personas = await runtime.personas.list_personas()
    return ok(
        {
            "accounts": [
                {
                    "id": item["id"],
                    "name": item["display_name"],
                    "has_mock": any(
                        instance["connection_mode"] == "mock" and instance["enabled"] for instance in item["instances"]
                    ),
                }
                for item in accounts
            ],
            "groups": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "platform_group_id": item["platform_group_id"],
                    "account_id": item["account_id"],
                    "enabled": item["enabled"],
                    "paused": item["paused"],
                    "persona_id": item["persona_id"],
                }
                for item in groups
            ],
            "personas": [{"id": item["id"], "name": item["name"], "mode": item["mode"]} for item in personas],
            "note": "模拟运行不会发送到 QQ，也不会写入消息日志；模拟事件注入仅对 Mock 连接器可用。",
        }
    )
