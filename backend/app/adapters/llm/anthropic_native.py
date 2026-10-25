"""Anthropic Messages API 原生 Provider（httpx 实现）。

只使用用户配置的 API Key 与 Base URL；不读取环境中的其他凭证。
请求/响应按官方 Messages API 映射，工具调用转换为 Anthropic tool_use。
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.adapters.llm.base import BaseLLMProvider
from app.core.errors import AppError, ErrorCode
from app.core.security import redact_text
from app.schemas.llm import ConnectionTestResult, LLMRequest, LLMResponse, LLMToolCall

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicNativeProvider(BaseLLMProvider):
    provider_type = "anthropic_native"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client: httpx.AsyncClient | None = None

    def _require_config(self) -> None:
        if not self.model:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 ID。", status_code=400)
        if not self.api_key:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 API Key。", status_code=400)

    def _get_client(self, timeout_seconds: float) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=timeout_seconds)
        return self._client

    def _endpoint(self) -> str:
        base = (self.base_url or DEFAULT_BASE_URL).rstrip("/")
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"

    def _classify_response(self, response: httpx.Response) -> AppError:
        body = redact_text(response.text[:500]) if response.text else ""
        details = {"status_code": response.status_code, "body": body}
        lowered = body.lower()
        if response.status_code in (401, 403):
            return AppError(
                ErrorCode.LLM_AUTH_FAILED,
                "Anthropic API 认证失败，请检查 API Key。",
                status_code=502,
                details=details,
            )
        if response.status_code == 404:
            return AppError(
                ErrorCode.LLM_MODEL_NOT_FOUND,
                "Anthropic 模型或接口不存在，请检查 Base URL 与模型 ID。",
                status_code=502,
                details=details,
            )
        if response.status_code == 413 or (response.status_code == 400 and "prompt is too long" in lowered):
            return AppError(
                ErrorCode.LLM_INVALID_RESPONSE,
                "上下文超出 Anthropic 模型长度限制，请缩短上下文或更换模型。",
                status_code=502,
                details=details,
            )
        if response.status_code == 400 and (
            "credit balance" in lowered or "insufficient" in lowered or "quota" in lowered
        ):
            return AppError(
                ErrorCode.LLM_QUOTA_EXCEEDED,
                "Anthropic 账户额度不足，请检查账单与用量限额。",
                status_code=502,
                details=details,
            )
        if response.status_code == 429:
            return AppError(
                ErrorCode.LLM_RATE_LIMITED,
                "Anthropic 请求被限流，请稍后再试或降低频率。",
                status_code=502,
                details=details,
                retryable=True,
            )
        if response.status_code in (500, 502, 503, 504, 529):
            return AppError(
                ErrorCode.LLM_NETWORK_ERROR,
                "Anthropic 服务暂时不可用。",
                status_code=502,
                details=details,
                retryable=True,
            )
        if response.status_code == 400:
            return AppError(
                ErrorCode.LLM_INVALID_RESPONSE,
                "Anthropic 请求参数无效，请检查模型 ID 与提示词长度。",
                status_code=502,
                details=details,
            )
        return AppError(
            ErrorCode.LLM_INVALID_RESPONSE,
            "Anthropic 接口返回错误。",
            status_code=502,
            details=details,
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self._require_config()
        system_extra, messages = _convert_messages(request.messages)
        system_prompt = "\n\n".join(part for part in (request.system_prompt, system_extra) if part)
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": messages,
            "max_tokens": max(1, int(request.max_output_tokens)),
            "temperature": min(max(float(request.temperature), 0.0), 1.0),
        }
        if system_prompt:
            payload["system"] = system_prompt
        tools = _convert_tools(request.tools)
        if tools:
            payload["tools"] = tools

        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        client = self._get_client(request.timeout_seconds or self.timeout_seconds)
        try:
            response = await client.post(self._endpoint(), json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise AppError(
                ErrorCode.LLM_TIMEOUT,
                "Anthropic 模型请求超时。",
                status_code=504,
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise AppError(
                ErrorCode.LLM_NETWORK_ERROR,
                "无法连接 Anthropic 服务，请检查网络与 Base URL。",
                status_code=502,
                details={"reason": type(exc).__name__},
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                ErrorCode.LLM_NETWORK_ERROR,
                "Anthropic 请求发生网络错误。",
                status_code=502,
                details={"reason": type(exc).__name__},
                retryable=True,
            ) from exc

        if response.status_code >= 400:
            raise self._classify_response(response)

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise AppError(
                ErrorCode.LLM_INVALID_RESPONSE,
                "Anthropic 返回了无法解析的响应。",
                status_code=502,
            ) from exc

        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise AppError(
                ErrorCode.LLM_INVALID_RESPONSE,
                "Anthropic 响应缺少 content。",
                status_code=502,
            )
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use":
                name = str(block.get("name") or "").strip()
                if not name:
                    continue
                arguments = block.get("input")
                tool_calls.append(
                    LLMToolCall(
                        id=str(block.get("id") or f"tool-{index}"),
                        name=name,
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
        usage = data.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            finish_reason=data.get("stop_reason"),
            request_id=response.headers.get("request-id") or response.headers.get("x-request-id"),
            raw={"model": data.get("model"), "type": data.get("type")},
        )

    async def test_connection(self) -> ConnectionTestResult:
        started = time.perf_counter()
        try:
            response = await self.generate(
                LLMRequest(
                    model=self.model,
                    messages=[{"role": "user", "content": "请只回复 OK"}],
                    temperature=0,
                    max_output_tokens=8,
                    timeout_seconds=min(self.timeout_seconds, 20.0),
                    purpose="test",
                )
            )
        except AppError as exc:
            return ConnectionTestResult(
                ok=False,
                message=exc.message,
                error_code=exc.code,
                details={
                    **exc.details,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000),
                },
            )
        return ConnectionTestResult(
            ok=True,
            message="Anthropic 模型连接成功。",
            details={
                "model": self.model,
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "reply_preview": response.text[:80],
            },
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    """把通用消息转换为 Anthropic 要求的结构。

    Anthropic 的 system 是顶层字段；消息角色只能是 user/assistant，且必须以 user 开始。
    这里合并连续同角色消息，避免不同调用方产生的消息序列被接口拒绝。
    """
    system_parts: list[str] = []
    converted: list[dict[str, str]] = []
    for item in messages:
        role = str(item.get("role") or "user")
        content = _flatten_content(item.get("content"))
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        normalized_role = "assistant" if role == "assistant" else "user"
        if converted and converted[-1]["role"] == normalized_role:
            converted[-1]["content"] = f"{converted[-1]['content']}\n\n{content}"
        else:
            converted.append({"role": normalized_role, "content": content})
    if not converted:
        converted.append({"role": "user", "content": "（继续对话）"})
    if converted[0]["role"] != "user":
        converted.insert(0, {"role": "user", "content": "（以下是对话历史，请继续）"})
    return "\n\n".join(system_parts), converted


def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") in (None, "text"):
                parts.append(str(part.get("text") or ""))
        return "\n".join(part for part in parts if part).strip()
    if content is None:
        return ""
    return str(content).strip()


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        nested = item.get("function")
        function: dict[str, Any] = nested if isinstance(nested, dict) else item
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        schema = function.get("parameters")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        converted.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "input_schema": schema,
            }
        )
    return converted
