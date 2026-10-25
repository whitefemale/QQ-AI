"""内置低风险工具：安全计算器与日期时间。"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from app.adapters.tools.base import Tool, ToolContext, ToolResult
from app.core.time import utcnow

_BINARY_OPERATORS: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS: dict[type, Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_ALLOWED_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}

_MAX_NODES = 60
_MAX_NUMBER = 1e12


class CalculatorArguments(BaseModel):
    expression: str = Field(
        min_length=1,
        max_length=200,
        description="算式，支持 + - * / // % **、括号、sqrt/abs/round/min/max。",
    )


class CalculatorTool(Tool):
    name = "calculator"
    description = "计算简单数学表达式。不能执行代码或访问外部资源。"
    risk_level = "low"
    timeout_seconds = 2.0
    input_model = CalculatorArguments

    async def run(self, arguments: BaseModel, context: ToolContext) -> ToolResult:
        assert isinstance(arguments, CalculatorArguments)
        try:
            value = _evaluate(arguments.expression)
        except _CalculationError as exc:
            return ToolResult(
                ok=False,
                content=f"计算失败：{exc}",
                error_code="TOOL_INPUT_INVALID",
                error_message=str(exc),
            )
        if isinstance(value, float) and value.is_integer():
            rendered = str(int(value))
        else:
            rendered = repr(round(value, 10))
        return ToolResult(ok=True, content=f"{arguments.expression} = {rendered}", data={"result": value})


class _CalculationError(ValueError):
    pass


def _evaluate(expression: str) -> float | int:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise _CalculationError("表达式语法不正确。") from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise _CalculationError("表达式过于复杂。")
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise _CalculationError("只允许数字常量。")
        if abs(node.value) > _MAX_NUMBER:
            raise _CalculationError("数字超出允许范围。")
        return node.value
    if isinstance(node, ast.BinOp):
        handler = _BINARY_OPERATORS.get(type(node.op))
        if handler is None:
            raise _CalculationError("不支持该运算符。")
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 8 or abs(left) > _MAX_NUMBER):
            raise _CalculationError("指数运算超出允许范围。")
        try:
            value = handler(left, right)
        except ZeroDivisionError as exc:
            raise _CalculationError("不能除以零。") from exc
        except OverflowError as exc:
            raise _CalculationError("计算结果超出范围。") from exc
        return _check_number(value)
    if isinstance(node, ast.UnaryOp):
        unary_handler = _UNARY_OPERATORS.get(type(node.op))
        if unary_handler is None:
            raise _CalculationError("不支持该运算符。")
        return _check_number(unary_handler(_eval_node(node.operand)))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCTIONS or node.keywords:
            raise _CalculationError("只允许 sqrt、abs、round、min、max 函数。")
        if len(node.args) > 5:
            raise _CalculationError("函数参数过多。")
        func = _ALLOWED_FUNCTIONS[node.func.id]
        args = [_eval_node(arg) for arg in node.args]
        try:
            return _check_number(func(*args))  # type: ignore[operator]
        except (ValueError, TypeError, OverflowError) as exc:
            raise _CalculationError("函数计算出错。") from exc
    raise _CalculationError("表达式包含不允许的内容。")


def _check_number(value: Any) -> float | int:
    if isinstance(value, complex):
        raise _CalculationError("不支持复数结果。")
    if not isinstance(value, int | float):
        raise _CalculationError("计算结果不是数字。")
    if isinstance(value, float) and not math.isfinite(value):
        raise _CalculationError("计算结果不是有限数字。")
    if abs(value) > _MAX_NUMBER:
        raise _CalculationError("计算结果超出范围。")
    return value


class DatetimeArguments(BaseModel):
    timezone: str = Field(default="Asia/Shanghai", max_length=64, description="IANA 时区名称，如 Asia/Shanghai。")
    offset_seconds: int = Field(default=0, ge=-315360000, le=315360000, description="相对当前时间的偏移秒数。")
    format: str | None = Field(default=None, max_length=64, description="可选的 strftime 格式。")


class DatetimeTool(Tool):
    name = "current_datetime"
    description = "查询指定时区的当前日期时间，可加入偏移。不能设置系统时间。"
    risk_level = "low"
    timeout_seconds = 2.0
    input_model = DatetimeArguments

    async def run(self, arguments: BaseModel, context: ToolContext) -> ToolResult:
        assert isinstance(arguments, DatetimeArguments)
        try:
            zone = ZoneInfo(arguments.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ToolResult(
                ok=False,
                content="查询失败：时区名称无效。",
                error_code="TOOL_INPUT_INVALID",
                error_message="无效的 IANA 时区名称。",
            )
        moment = (utcnow() + timedelta(seconds=arguments.offset_seconds)).astimezone(zone)
        formatted = moment.strftime(arguments.format) if arguments.format else moment.strftime("%Y-%m-%d %H:%M:%S %Z")
        return ToolResult(
            ok=True,
            content=(
                f"{arguments.timezone} 当前时间：{formatted}（UTC：{moment.astimezone(ZoneInfo('UTC')).isoformat()}）"
            ),
            data={
                "timezone": arguments.timezone,
                "iso": moment.isoformat(),
                "offset_seconds": arguments.offset_seconds,
                "weekday": moment.isoweekday(),
            },
        )


BUILTIN_TOOLS: list[Tool] = [CalculatorTool(), DatetimeTool()]
