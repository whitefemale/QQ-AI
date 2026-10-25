"""工具接口与调用上下文。

安全原则：工具只能访问明确声明的能力；默认不提供 Shell、任意文件读写或任意网络请求。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.errors import AppError, ErrorCode


class ToolResult(BaseModel):
    ok: bool = True
    content: str = ""
    error_code: str | None = None
    error_message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ToolContext:
    account_id: str | None = None
    group_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    member_id: str | None = None
    allow_high_risk: bool = False
    allowed_tools: list[str] | None = None
    calls_used: int = 0
    max_calls: int = 3
    source: str = "message"


class Tool(ABC):
    name: str = ""
    description: str = ""
    risk_level: str = "low"  # low / medium / high
    required_permissions: tuple[str, ...] = ()
    timeout_seconds: float = 5.0
    input_model: type[BaseModel] | None = None

    def parameters_schema(self) -> dict[str, Any]:
        if self.input_model is None:
            return {"type": "object", "properties": {}}
        return self.input_model.model_json_schema()

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema(),
            },
        }

    def validate_arguments(self, arguments: dict[str, Any]) -> BaseModel:
        if not isinstance(arguments, dict):
            raise AppError(ErrorCode.TOOL_INPUT_INVALID, "工具参数必须是 JSON 对象。", status_code=400)
        if self.input_model is None:
            return BaseModel()
        try:
            return self.input_model.model_validate(arguments)
        except ValidationError as exc:
            fields = "、".join(".".join(str(part) for part in error["loc"]) or "参数" for error in exc.errors())
            raise AppError(
                ErrorCode.TOOL_INPUT_INVALID,
                f"工具参数不合法：{fields}。",
                status_code=400,
            ) from exc

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        payload = self.validate_arguments(arguments)
        return await self.run(payload, context)

    @abstractmethod
    async def run(self, arguments: BaseModel, context: ToolContext) -> ToolResult:
        raise NotImplementedError
