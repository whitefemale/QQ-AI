"""工具、插件与安全测试接口。第三方插件不加载、不执行。"""

from __future__ import annotations

from typing import Any

from app.adapters.tools.base import ToolContext
from app.api.deps import as_payload, get_actor, get_runtime
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.tool import ToolRecord
from app.runtime import AppRuntime
from app.services.audit import write_audit
from fastapi import APIRouter, Body, Depends
from sqlalchemy import select

router = APIRouter()


async def _tool_items(runtime: AppRuntime) -> list[dict[str, Any]]:
    public = {item["name"]: dict(item) for item in runtime.tool_registry.public()}
    async with runtime.database.session() as session:
        records = list((await session.execute(select(ToolRecord))).scalars())
    for record in records:
        item = public.get(record.name)
        if item is None:
            continue
        item["id"] = record.id
        item["enabled"] = record.enabled
        item["description"] = record.description
        item["runtime_status"] = "available" if record.enabled else "disabled"
    return list(public.values())


@router.get("/tools")
async def list_tools(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(
        {
            "items": await _tool_items(runtime),
            "note": "内置工具只能使用已声明的低风险能力；不存在任意 Shell/文件读写工具。",
        }
    )


@router.post("/tools/sync")
async def sync_tools(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    from app.adapters.tools.executor import sync_tool_records

    count = await sync_tool_records(runtime.database, runtime.tool_registry)
    return ok({"synced": count})


@router.post("/tools/{tool_name}/test")
async def test_tool(
    tool_name: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    tool = runtime.tool_registry.get(tool_name)
    if tool is None:
        raise AppError(ErrorCode.TOOL_NOT_FOUND, "工具不存在或未注册。", status_code=404)
    data = as_payload(payload)
    raw_arguments: Any = data.get("arguments")
    arguments: dict[str, Any] = raw_arguments if isinstance(raw_arguments, dict) else {}
    context = ToolContext(
        source="admin-test",
        allow_high_risk=False,
        max_calls=1,
    )
    result = await runtime.tool_executor.execute(tool_name, arguments, context)
    await write_audit(
        runtime.database,
        action="tool.test",
        target_type="tool",
        target_id=tool_name,
        details={"ok": result.ok, "error_code": result.error_code},
        actor=actor,
    )
    return ok(result.model_dump())


@router.patch("/tools/{tool_name}")
async def set_tool_enabled(
    tool_name: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    enabled = bool(as_payload(payload).get("enabled"))
    async with runtime.database.session() as session:
        record = await session.scalar(select(ToolRecord).where(ToolRecord.name == tool_name))
        if record is None:
            raise AppError(ErrorCode.TOOL_NOT_FOUND, "工具尚未同步到数据库。", status_code=404)
        record.enabled = enabled
        await session.commit()
    await write_audit(
        runtime.database,
        action="tool.enable" if enabled else "tool.disable",
        target_type="tool",
        target_id=tool_name,
        actor=actor,
    )
    items = await _tool_items(runtime)
    return ok(next(item for item in items if item["name"] == tool_name))


@router.get("/plugins")
async def list_plugins(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(
        {
            "items": await runtime.plugins.list_plugins(),
            "load_errors": runtime.plugins.load_errors,
            "note": "当前版本只登记插件清单，不加载或执行第三方代码。",
        }
    )


@router.post("/plugins/sync")
async def sync_plugins(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    result = await runtime.plugins.sync()
    return ok(
        {
            "loaded": len(result.manifests),
            "errors": [error.model_dump() for error in result.errors],
            "items": await runtime.plugins.list_plugins(),
        }
    )


@router.get("/plugins/{plugin_id}")
async def get_plugin(plugin_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.plugins.get(plugin_id))


@router.get("/plugins/{plugin_id}/health")
async def plugin_health(plugin_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.plugins.health(plugin_id))


@router.post("/plugins/{plugin_id}/enable")
async def enable_plugin(
    plugin_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    data = as_payload(payload)
    enabled = bool(data.get("enabled", True))
    result = await runtime.plugins.set_enabled(plugin_id, enabled)
    await write_audit(
        runtime.database,
        action="plugin.enable" if enabled else "plugin.disable",
        target_type="plugin",
        target_id=plugin_id,
        actor=actor,
    )
    return ok(result)


@router.post("/plugins/{plugin_id}/approve")
async def approve_plugin_permissions(
    plugin_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    approved = bool(as_payload(payload).get("approved", True))
    result = await runtime.plugins.approve_permissions(plugin_id, approved)
    await write_audit(
        runtime.database,
        action="plugin.permissions.approve" if approved else "plugin.permissions.revoke",
        target_type="plugin",
        target_id=plugin_id,
        actor=actor,
    )
    return ok(result)
