"""Anthropic 原生 Provider：请求/响应映射与错误分类（不访问真实网络）。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from app.adapters.llm.anthropic_native import AnthropicNativeProvider
from app.core.errors import AppError, ErrorCode
from app.schemas.llm import LLMRequest


def _provider(base_url: str = "https://api.example.invalid/v1") -> AnthropicNativeProvider:
    return AnthropicNativeProvider(
        provider_id="p-anthropic",
        name="测试 Anthropic",
        model="claude-sonnet-5",
        base_url=base_url,
        api_key="sk-ant-test-secret",
        timeout_seconds=10,
        max_output_tokens=800,
        temperature=0.7,
    )


async def _generate(provider: AnthropicNativeProvider, request: LLMRequest | None = None) -> Any:
    return await provider.generate(
        request
        or LLMRequest(
            model="claude-sonnet-5",
            system_prompt="主系统规则",
            messages=[
                {"role": "assistant", "content": "历史回复"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "继续"},
                {"role": "system", "content": "补充规则"},
            ],
            temperature=1.4,
            max_output_tokens=256,
        )
    )


async def test_generate_maps_messages_tools_and_usage() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"request-id": "req_anthropic_1"},
            json={
                "model": "claude-sonnet-5",
                "content": [
                    {"type": "text", "text": "你好，"},
                    {"type": "text", "text": "有什么可以帮你？"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "calculator",
                        "input": {"expression": "1+1"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 21, "output_tokens": 9},
            },
        )

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        request = LLMRequest(
            model="",
            system_prompt="主系统规则",
            messages=[
                {"role": "assistant", "content": "历史回复"},
                {"role": "user", "content": "你好"},
                {"role": "user", "content": "继续"},
                {"role": "system", "content": "补充规则"},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "description": "计算表达式",
                        "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}},
                    },
                }
            ],
            temperature=1.4,
            max_output_tokens=256,
        )
        response = await _generate(provider, request)
    finally:
        await provider.close()

    assert captured["url"] == "https://api.example.invalid/v1/messages"
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["x-api-key"] == "sk-ant-test-secret"
    assert headers["anthropic-version"] == "2023-06-01"

    payload = captured["json"]
    assert payload["model"] == "claude-sonnet-5"
    assert payload["system"] == "主系统规则\n\n补充规则"
    assert payload["max_tokens"] == 256
    assert payload["temperature"] == 1.0
    assert payload["messages"] == [
        {"role": "user", "content": "（以下是对话历史，请继续）"},
        {"role": "assistant", "content": "历史回复"},
        {"role": "user", "content": "你好\n\n继续"},
    ]
    assert payload["tools"] == [
        {
            "name": "calculator",
            "description": "计算表达式",
            "input_schema": {"type": "object", "properties": {"expression": {"type": "string"}}},
        }
    ]

    assert response.text == "你好，有什么可以帮你？"
    assert response.input_tokens == 21
    assert response.output_tokens == 9
    assert response.finish_reason == "tool_use"
    assert response.request_id == "req_anthropic_1"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "toolu_1"
    assert response.tool_calls[0].name == "calculator"
    assert response.tool_calls[0].arguments == {"expression": "1+1"}


async def test_base_url_without_v1_gets_messages_path() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "OK"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    provider = _provider("https://anthropic.example.invalid")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        response = await _generate(provider)
    finally:
        await provider.close()
    assert captured["url"] == "https://anthropic.example.invalid/v1/messages"
    assert response.text == "OK"


@pytest.mark.parametrize(
    ("status", "body", "expected_code", "retryable"),
    [
        (
            401,
            {"error": {"type": "authentication_error", "message": "invalid api key"}},
            ErrorCode.LLM_AUTH_FAILED,
            False,
        ),
        (
            404,
            {"error": {"type": "not_found_error", "message": "model not found"}},
            ErrorCode.LLM_MODEL_NOT_FOUND,
            False,
        ),
        (
            400,
            {"error": {"type": "invalid_request_error", "message": "Your credit balance is too low"}},
            ErrorCode.LLM_QUOTA_EXCEEDED,
            False,
        ),
        (429, {"error": {"type": "rate_limit_error", "message": "slow down"}}, ErrorCode.LLM_RATE_LIMITED, True),
        (529, {"error": {"type": "overloaded_error", "message": "overloaded"}}, ErrorCode.LLM_NETWORK_ERROR, True),
    ],
)
async def test_error_classification(
    status: int,
    body: dict[str, Any],
    expected_code: str,
    retryable: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError) as caught:
            await _generate(provider)
    finally:
        await provider.close()

    assert caught.value.code == expected_code
    assert caught.value.retryable is retryable
    assert caught.value.details["status_code"] == status


async def test_context_length_error_has_actionable_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"type": "invalid_request_error", "message": "prompt is too long: 210000 tokens"}},
        )

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError) as caught:
            await _generate(provider)
    finally:
        await provider.close()
    assert caught.value.code == ErrorCode.LLM_INVALID_RESPONSE
    assert "长度限制" in caught.value.message


async def test_connection_test_reports_failure_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"type": "authentication_error", "message": "bad key"}})

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await provider.test_connection()
    finally:
        await provider.close()
    assert result.ok is False
    assert result.error_code == ErrorCode.LLM_AUTH_FAILED
    assert result.message
    assert result.details["elapsed_ms"] >= 0
