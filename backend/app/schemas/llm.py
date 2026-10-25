"""LLM 请求 / 响应 DTO。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class LLMRequest(BaseModel):
    model: str
    system_prompt: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = 0.7
    max_output_tokens: int = 800
    timeout_seconds: float = 45.0
    purpose: Literal[
        "reply",
        "persona_growth",
        "memory_extraction",
        "test",
        "summary",
        "playground",
    ] = "reply"
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    text: str = ""
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    request_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    error_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
