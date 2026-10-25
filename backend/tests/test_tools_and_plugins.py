from __future__ import annotations

import pytest
from app.adapters.tools.base import Tool, ToolContext, ToolResult
from app.adapters.tools.builtin import CalculatorTool
from app.adapters.tools.executor import ToolExecutor
from app.adapters.tools.registry import ToolRegistry
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import Database
from app.models.tool import ToolRun
from app.plugins.manifest import parse_manifest
from app.plugins.registry import PluginService
from sqlalchemy import func, select


async def test_calculator_is_safe(settings: Settings, database: Database) -> None:
    registry = ToolRegistry([CalculatorTool()])
    executor = ToolExecutor(database, registry, settings)
    context = ToolContext(max_calls=3)

    ok = await executor.execute("calculator", {"expression": "2*(3+4)"}, context)
    assert ok.ok is True
    assert "14" in ok.content

    malicious = await executor.execute("calculator", {"expression": "__import__('os').system('echo hi')"}, context)
    assert malicious.ok is False
    assert malicious.error_code == "TOOL_INPUT_INVALID"

    async with database.session() as session:
        count = await session.scalar(select(func.count()).select_from(ToolRun))
    assert count == 2


async def test_high_risk_tool_requires_authorization(settings: Settings, database: Database) -> None:
    class Dangerous(Tool):
        name = "dangerous"
        description = "测试用高风险工具"
        risk_level = "high"
        required_permissions = ("tools:invoke",)

        async def run(self, arguments, context) -> ToolResult:  # type: ignore[no-untyped-def]
            return ToolResult(content="不应执行")

    registry = ToolRegistry([Dangerous()])
    executor = ToolExecutor(database, registry, settings)
    denied = await executor.execute("dangerous", {}, ToolContext())
    assert denied.ok is False
    assert denied.error_code == "TOOL_PERMISSION_DENIED"


async def test_plugin_validation_and_builtin_sync(settings: Settings, database: Database) -> None:
    with pytest.raises(AppError):
        parse_manifest({"id": "Bad Id", "name": "x"})
    with pytest.raises(AppError):
        parse_manifest({"id": "ok.plugin", "name": "x", "permissions": ["filesystem:everything"]})
    with pytest.raises(AppError):
        parse_manifest({"id": "ok.plugin", "name": "x", "entrypoint": "C:/run.exe"})

    service = PluginService(database, settings)
    await service.sync()
    plugins = await service.list_plugins()
    core = next(item for item in plugins if item["id"] == "builtin.core-tools")
    assert core["enabled"] is True
    assert core["runtime_status"] == "builtin_active"

    disabled = await service.set_enabled("builtin.core-tools", False)
    assert disabled["enabled"] is False
    assert await service.is_core_tools_enabled() is False

    await service.approve_permissions("builtin.core-tools", False)
    with pytest.raises(AppError):
        await service.set_enabled("builtin.core-tools", True)
