"""工具、插件与安全测试接口。第三方插件不加载、不执行。"""

from __future__ import annotations

from typing import Any

from app.adapters.tools.base import ToolContext
from app.api.deps import as_payload, get_actor, get_runtime
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.core.time import iso_utc, utcnow
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


@router.get("/extensions/capabilities")
async def extension_capabilities(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    """统一扩展契约与真实执行状态；每一行都区分契约、实现与运行时。"""
    tools = await _tool_items(runtime)
    plugins = await runtime.plugins.list_plugins()
    media = await runtime.providers.capability_overview()
    media_providers = await runtime.providers.list_media_providers()
    contracts = [
        {
            "kind": "chat_adapter",
            "interface": "BaseQQAdapter",
            "state": "available",
            "execution": "in_process",
            "implementations": [item["value"] for item in runtime.manager.adapter_factory.modes()],
            "pipeline_dependency": "MessagePipeline 与 OutboxService 只依赖 BaseQQAdapter。",
            "guarantees": [
                "新增适配器需实现 capabilities/connect/disconnect/send_text。",
                "未实现的能力必须在 AdapterCapabilities 中为 false，不得由业务层假设。",
                "不得修改消息流水线即可接入；连接器差异由适配器隔离。",
            ],
        },
        {
            "kind": "llm_provider",
            "interface": "BaseLLMProvider",
            "state": "available",
            "execution": "remote_or_mock",
            "implementations": ["mock", "openai_compatible", "anthropic_native"],
            "planned": ["official"],
            "pipeline_dependency": "LLMGateway 通过 BaseLLMProvider 调用，不直接依赖具体服务商。",
            "guarantees": [
                "真实失败不自动回退到 Mock。",
                "未配置 Key/Base URL/模型 ID 时明确拒绝，不发起伪调用。",
                "调用前预算检查；用量与费用状态真实记录。",
            ],
        },
        {
            "kind": "media_provider",
            "interface": "BaseMediaProvider",
            "state": "partial",
            "execution": "job_or_contract_only",
            "implementations": [item["provider_id"] for item in media_providers],
            "pipeline_dependency": "CapabilityRouter 选择 Provider；MediaJobService 只执行已实现的任务类型。",
            "guarantees": [
                "未配置 Provider 时不执行伪实现；任务创建被拒绝并如实说明。",
                "Mock 结果始终标记 is_mock，费用视为 0，不代表真实识别。",
                "停用 Provider 会取消该能力下排队与运行中的任务，运行结果保存前再次检查取消状态。",
            ],
        },
        {
            "kind": "tool",
            "interface": "Tool",
            "state": "available",
            "execution": "in_process",
            "implementations": [item["name"] for item in tools],
            "pipeline_dependency": "ToolExecutor 只执行启动时固定注册的工具。",
            "guarantees": [
                "只有内置 calculator/current_datetime；不存在任意 Shell、文件或 URL 工具。",
                "群级默认关闭；高风险与需权限工具默认拒绝。",
                "每次执行有超时、参数校验与审计，结果视为不可信数据。",
            ],
        },
        {
            "kind": "plugin",
            "interface": "PluginManifest + PluginRuntime（规划）",
            "state": "manifest_only",
            "execution": "not_executed",
            "implementations": [item["id"] for item in plugins],
            "pipeline_dependency": "插件不进入消息流水线；仅登记清单与权限。",
            "guarantees": [
                "不加载、不执行第三方代码；entrypoint 禁止本地任意代码。",
                "启用第三方插件返回 OPERATION_PLANNED。",
                "未来执行必须满足独立沙箱、权限清单、确认、签名、超时、资源限制、审计与停用。",
            ],
        },
    ]
    return ok(
        {
            "contracts": contracts,
            "media": media,
            "tools": tools,
            "plugins": plugins,
            "checked_at": iso_utc(utcnow()),
            "notes": [
                "以上状态来自代码注册表与本地数据库，不是外部探测结果。",
                "未配置的真实视觉/语音/插件能力不会调用伪实现，也不会被标记为可用。",
                "停用媒体 Provider 会立即取消对应能力下排队与运行中的任务。",
            ],
        }
    )


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
