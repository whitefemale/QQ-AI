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
    """媒体 Provider 与旧调用的连通性结果；LLM Provider 统一走网关测试。"""

    ok: bool
    message: str
    error_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class LLMModelInfo(BaseModel):
    id: str
    display_name: str | None = None
    created_at: str | None = None
    owned_by: str | None = None


class ModelListResult(BaseModel):
    supported: bool = True
    state: str = "available"
    models: list[LLMModelInfo] = Field(default_factory=list)
    current_model_listed: bool | None = None
    truncated: bool = False
    fetched_at: str | None = None
    message: str | None = None
    error_code: str | None = None
    note: str | None = None


class ProviderTestUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost: float | None = None
    currency: str = "USD"
    cost_status: Literal["estimated", "mock_zero", "unavailable"] = "unavailable"
    note: str = ""


class ProviderTestRecord(BaseModel):
    """持久化的显式测试证据，只包含白名单元数据与截断预览。"""

    kind: Literal["connectivity", "generation"]
    outcome: Literal["success", "failure", "cancelled"]
    ok: bool
    tested_at: str
    latency_ms: int | None = None
    attempts: int = 1
    model: str | None = None
    is_mock: bool = False
    error_code: str | None = None
    message: str | None = None
    reply_preview: str | None = None
    upstream_request_id: str | None = None
    usage: ProviderTestUsage | None = None


class ProviderTestResult(ProviderTestRecord):
    provider_id: str
    provider_type: str
    provider_enabled: bool
    billable: bool = False
    operation_id: str | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None
    next_step: str | None = None
    text: str | None = None
