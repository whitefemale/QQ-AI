"""内置工具注册表。第三方工具运行时不在 P0 范围内。"""

from __future__ import annotations

from app.adapters.tools.base import Tool
from app.adapters.tools.builtin import BUILTIN_TOOLS
from app.core.errors import AppError, ErrorCode


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools if tools is not None else BUILTIN_TOOLS:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError("工具必须有名称。")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def require(self, name: str) -> Tool:
        tool = self.get(name)
        if tool is None:
            raise AppError(ErrorCode.TOOL_NOT_FOUND, "工具不存在或未注册。", status_code=404)
        return tool

    def list_tools(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda item: item.name)

    def definitions(self, names: list[str] | None = None) -> list[dict[str, object]]:
        allowed = set(names) if names is not None else None
        return [tool.definition() for tool in self.list_tools() if allowed is None or tool.name in allowed]

    def public(self) -> list[dict[str, object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "risk_level": tool.risk_level,
                "required_permissions": list(tool.required_permissions),
                "timeout_seconds": tool.timeout_seconds,
                "input_schema": tool.parameters_schema(),
                "builtin": True,
                "runtime_status": "available",
            }
            for tool in self.list_tools()
        ]


def build_default_tool_registry() -> ToolRegistry:
    return ToolRegistry()
