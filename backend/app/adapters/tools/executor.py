"""工具权限引擎与执行器：参数校验、风险拦截、超时、次数上限与运行记录。"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.tools.base import Tool, ToolContext, ToolResult
from app.adapters.tools.registry import ToolRegistry
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.security import redact_value
from app.db.session import Database
from app.models.tool import ToolRecord, ToolRun
from app.plugins.registry import PluginService

_SUMMARY_LIMIT = 800


def _summarize(value: str | None, limit: int = _SUMMARY_LIMIT) -> str | None:
    if value is None:
        return None
    redacted = redact_value(value)
    text = str(redacted)
    return text if len(text) <= limit else text[:limit] + "…"


def _safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_value(arguments)
    if not isinstance(redacted, dict):
        return {"value": redacted}
    try:
        json.dumps(redacted, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"value": "[无法序列化的参数]"}
    return redacted


class ToolExecutor:
    def __init__(
        self,
        database: Database,
        registry: ToolRegistry,
        settings: Settings,
        plugin_service: PluginService | None = None,
    ) -> None:
        self.database = database
        self.registry = registry
        self.settings = settings
        self.plugin_service = plugin_service

    async def _tool_record(self, session: AsyncSession, name: str) -> ToolRecord | None:
        return await session.scalar(select(ToolRecord).where(ToolRecord.name == name))

    async def _record_run(
        self,
        *,
        tool: Tool | None,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        result: ToolResult,
        status: str,
        duration_ms: int,
        tool_id: str | None = None,
    ) -> None:
        try:
            async with self.database.session() as session:
                session.add(
                    ToolRun(
                        tool_id=tool_id,
                        tool_name=name,
                        message_id=context.message_id,
                        conversation_id=context.conversation_id,
                        arguments_json=_safe_arguments(arguments),
                        status=status,
                        result_summary=_summarize(result.content or result.error_message),
                        error_code=result.error_code,
                        duration_ms=duration_ms,
                    )
                )
                await session.commit()
        except Exception:  # 运行记录失败不得影响工具结果
            return

    async def execute(self, tool_name: str, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        tool = self.registry.get(tool_name)
        if tool is None:
            result = ToolResult(
                ok=False,
                content="工具不存在或未注册。",
                error_code=ErrorCode.TOOL_NOT_FOUND,
                error_message="工具不存在或未注册。",
            )
            await self._record_run(
                tool=None,
                name=tool_name,
                arguments=arguments,
                context=context,
                result=result,
                status="failed",
                duration_ms=0,
            )
            return result

        denied = await self._check_permission(tool, context)
        if denied is not None:
            await self._record_run(
                tool=tool,
                name=tool_name,
                arguments=arguments,
                context=context,
                result=denied,
                status="denied",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return denied

        tool_record: ToolRecord | None = None
        try:
            async with self.database.session() as session:
                tool_record = await self._tool_record(session, tool_name)
            if tool_record is not None and not tool_record.enabled:
                result = ToolResult(
                    ok=False,
                    content="该工具已在控制台停用。",
                    error_code=ErrorCode.TOOL_DISABLED,
                    error_message="该工具已在控制台停用。",
                )
                await self._record_run(
                    tool=tool,
                    name=tool_name,
                    arguments=arguments,
                    context=context,
                    result=result,
                    status="denied",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    tool_id=tool_record.id,
                )
                return result
        except Exception:
            tool_record = None

        context.calls_used += 1
        status = "success"
        try:
            result = await asyncio.wait_for(tool.execute(arguments, context), timeout=tool.timeout_seconds)
            if not result.ok:
                status = "failed"
        except TimeoutError:
            status = "timeout"
            result = ToolResult(
                ok=False,
                content="工具执行超时。",
                error_code=ErrorCode.TOOL_TIMEOUT,
                error_message="工具执行超时。",
            )
        except AppError as exc:
            status = "failed"
            result = ToolResult(ok=False, content=exc.message, error_code=exc.code, error_message=exc.message)
        except Exception as exc:  # pragma: no cover - 防御性
            status = "failed"
            message = "工具执行失败。"
            result = ToolResult(
                ok=False,
                content=message,
                error_code=ErrorCode.TOOL_FAILED,
                error_message=f"{message}（{type(exc).__name__}）",
            )

        await self._record_run(
            tool=tool,
            name=tool_name,
            arguments=arguments,
            context=context,
            result=result,
            status=status,
            duration_ms=int((time.perf_counter() - started) * 1000),
            tool_id=tool_record.id if tool_record else None,
        )
        return result

    async def _check_permission(self, tool: Tool, context: ToolContext) -> ToolResult | None:
        if self.plugin_service is not None and not await self.plugin_service.is_core_tools_enabled():
            return ToolResult(
                ok=False,
                content="内置工具模块已停用。",
                error_code=ErrorCode.TOOL_DISABLED,
                error_message="内置工具模块已在扩展管理中停用。",
            )
        if context.allowed_tools is not None and tool.name not in context.allowed_tools:
            return ToolResult(
                ok=False,
                content="该群未允许此工具。",
                error_code=ErrorCode.TOOL_PERMISSION_DENIED,
                error_message="该群未允许此工具。",
            )
        if context.calls_used >= context.max_calls:
            return ToolResult(
                ok=False,
                content="本轮工具调用次数已达上限。",
                error_code=ErrorCode.TOOL_PERMISSION_DENIED,
                error_message="本轮工具调用次数已达上限。",
            )
        if tool.risk_level == "high" and not context.allow_high_risk:
            return ToolResult(
                ok=False,
                content="高风险工具需要显式授权后才能使用。",
                error_code=ErrorCode.TOOL_PERMISSION_DENIED,
                error_message="高风险工具需要显式授权后才能使用。",
            )
        if tool.required_permissions and not context.allow_high_risk:
            return ToolResult(
                ok=False,
                content="该工具所需的权限尚未授权。",
                error_code=ErrorCode.TOOL_PERMISSION_DENIED,
                error_message="该工具所需的权限尚未授权。",
            )
        return None


async def sync_tool_records(database: Database, registry: ToolRegistry) -> int:
    """把内置工具同步到数据库，供控制台启停与审计引用。"""
    count = 0
    async with database.session() as session:
        existing = {record.name: record for record in (await session.execute(select(ToolRecord))).scalars()}
        for tool in registry.list_tools():
            record = existing.get(tool.name)
            if record is None:
                record = ToolRecord(
                    name=tool.name,
                    description=tool.description,
                    tool_type="builtin",
                    input_schema_json=tool.parameters_schema(),
                    risk_level=tool.risk_level,
                    required_permissions_json=list(tool.required_permissions),
                    timeout_seconds=tool.timeout_seconds,
                    enabled=True,
                    builtin=True,
                )
                session.add(record)
            else:
                record.description = tool.description
                record.input_schema_json = tool.parameters_schema()
                record.risk_level = tool.risk_level
                record.required_permissions_json = list(tool.required_permissions)
                record.timeout_seconds = tool.timeout_seconds
                record.builtin = True
            count += 1
        await session.commit()
    return count
