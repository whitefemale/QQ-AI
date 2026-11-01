"""OpenAI 兼容 Provider：请求/响应映射、错误分类与模型列表（不访问真实网络）。"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from app.adapters.llm.openai_compatible import OpenAICompatibleProvider
from app.core.errors import AppError, ErrorCode
from app.schemas.llm import LLMRequest


def _provider(base_url: str = "https://llm.example.invalid/v1") -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        provider_id="p-openai",
        name="测试 OpenAI 兼容",
        model="demo-model",
        base_url=base_url,
        api_key="sk-test-secret",
        timeout_seconds=12,
        max_output_tokens=800,
        temperature=0.7,
    )


async def _generate(provider: OpenAICompatibleProvider, request: LLMRequest | None = None) -> Any:
    return await provider.generate(
        request
        or LLMRequest(
            model="demo-model",
            system_prompt="系统规则",
            messages=[{"role": "user", "content": "你好"}],
            temperature=0.3,
            max_output_tokens=64,
        )
    )


async def test_generate_maps_request_tools_usage_and_timeout() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        captured["timeout"] = request.extensions.get("timeout")
        return httpx.Response(
            200,
            headers={"x-request-id": "req_openai_1"},
            json={
                "model": "demo-model",
                "choices": [
                    {
                        "message": {
                            "content": "你好！",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            },
        )

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        response = await _generate(
            provider,
            LLMRequest(
                model="demo-model",
                system_prompt="系统规则",
                messages=[{"role": "user", "content": "1+1 等于几"}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}},
                        },
                    }
                ],
                temperature=0.3,
                max_output_tokens=64,
                timeout_seconds=5,
                purpose="test",
            ),
        )
    finally:
        await provider.close()

    assert captured["url"] == "https://llm.example.invalid/v1/chat/completions"
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["authorization"] == "Bearer sk-test-secret"
    assert captured["json"]["messages"] == [
        {"role": "system", "content": "系统规则"},
        {"role": "user", "content": "1+1 等于几"},
    ]
    assert captured["json"]["max_tokens"] == 64
    assert captured["json"]["tools"][0]["function"]["name"] == "calculator"
    assert captured["timeout"] == {"connect": 5, "read": 5, "write": 5, "pool": 5}

    assert response.text == "你好！"
    assert response.input_tokens == 12
    assert response.output_tokens == 6
    assert response.finish_reason == "tool_calls"
    assert response.request_id == "req_openai_1"
    assert response.tool_calls[0].arguments == {"expression": "1+1"}


@pytest.mark.parametrize(
    ("status", "body", "expected_code", "retryable", "safety"),
    [
        (401, {"error": {"message": "bad key"}}, ErrorCode.LLM_AUTH_FAILED, False, "none"),
        (402, {"error": {"message": "no credit"}}, ErrorCode.LLM_QUOTA_EXCEEDED, False, "none"),
        (404, {"error": {"message": "model missing"}}, ErrorCode.LLM_MODEL_NOT_FOUND, False, "none"),
        (429, {"error": {"message": "slow down"}}, ErrorCode.LLM_RATE_LIMITED, True, "safe"),
        (
            429,
            {"error": {"message": "insufficient quota"}},
            ErrorCode.LLM_QUOTA_EXCEEDED,
            False,
            "none",
        ),
        (500, {"error": {"message": "server down"}}, ErrorCode.LLM_NETWORK_ERROR, True, "safe"),
        (503, {"error": {"message": "unavailable"}}, ErrorCode.LLM_NETWORK_ERROR, True, "safe"),
        (400, {"error": {"message": "bad parameter"}}, ErrorCode.LLM_INVALID_RESPONSE, False, "none"),
    ],
)
async def test_error_classification(
    status: int,
    body: dict[str, Any],
    expected_code: str,
    retryable: bool,
    safety: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"x-request-id": "req_err"}, json=body)

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
    assert caught.value.details["retry_safety"] == safety
    assert caught.value.details["upstream_request_id"] == "req_err"


async def test_rate_limit_retry_after_is_parsed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "3.5"},
            json={"error": {"message": "slow down"}},
        )

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError) as caught:
            await _generate(provider)
    finally:
        await provider.close()

    assert caught.value.details["retry_after_seconds"] == 3.5
    assert caught.value.details["retry_safety"] == "safe"


async def test_connect_error_is_safe_but_read_timeout_is_ambiguous() -> None:
    def connect_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(connect_handler))
    try:
        with pytest.raises(AppError) as caught:
            await _generate(provider)
    finally:
        await provider.close()
    assert caught.value.code == ErrorCode.LLM_NETWORK_ERROR
    assert caught.value.details["retry_safety"] == "safe"
    assert caught.value.retryable is True

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    try:
        with pytest.raises(AppError) as caught:
            await _generate(provider)
    finally:
        await provider.close()
    assert caught.value.code == ErrorCode.LLM_TIMEOUT
    assert caught.value.details["retry_safety"] == "ambiguous"
    assert caught.value.retryable is True


async def test_malformed_response_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError) as caught:
            await _generate(provider)
    finally:
        await provider.close()
    assert caught.value.code == ErrorCode.LLM_INVALID_RESPONSE

    def missing_choices(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(missing_choices))
    try:
        with pytest.raises(AppError) as caught:
            await _generate(provider)
    finally:
        await provider.close()
    assert caught.value.code == ErrorCode.LLM_INVALID_RESPONSE


async def test_models_supports_data_and_top_level_list() -> None:
    payloads = [
        {
            "data": [
                {"id": "demo-model", "owned_by": "vendor"},
                {"id": "other-model", "created": 1700000000},
                {"id": "demo-model"},
            ]
        },
        [
            {"id": "demo-model", "owned_by": "vendor"},
            {"id": "other-model", "created": 1700000000},
        ],
    ]
    for payload in payloads:

        def handler(request: httpx.Request, payload: Any = payload) -> httpx.Response:
            return httpx.Response(200, json=payload)

        provider = _provider("https://llm.example.invalid/v1/")
        provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            result = await provider.list_models(timeout_seconds=2)
        finally:
            await provider.close()

        assert result.supported is True
        assert result.state == "available"
        assert [item.id for item in result.models] == ["demo-model", "other-model"]
        assert result.models[0].owned_by == "vendor"
        assert result.models[1].created_at
        assert result.current_model_listed is True


@pytest.mark.parametrize("status", [404, 405, 501])
async def test_models_missing_endpoint_is_unsupported(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "no models endpoint"}})

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await provider.list_models()
    finally:
        await provider.close()

    assert result.supported is False
    assert result.state == "unsupported"
    assert result.models == []
    assert "手动填写" in (result.message or "")


async def test_models_auth_failure_is_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    provider = _provider()
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError) as caught:
            await provider.list_models()
    finally:
        await provider.close()

    assert caught.value.code == ErrorCode.LLM_AUTH_FAILED


async def test_model_list_requires_base_url_and_key_but_not_model() -> None:
    provider = OpenAICompatibleProvider(
        provider_id="p-no-model",
        name="缺模型",
        model="",
        base_url="https://llm.example.invalid/v1",
        api_key="sk-test-secret",
        timeout_seconds=5,
        max_output_tokens=100,
        temperature=0.7,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "demo-model"}]})

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await provider.list_models()
    finally:
        await provider.close()
    assert result.supported is True
    assert result.current_model_listed is None
