"""OpenAI-compatible Chat Completions Provider（httpx 实现）。"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.adapters.llm.base import BaseLLMProvider
from app.core.errors import AppError, ErrorCode
from app.core.security import redact_text
from app.schemas.llm import ConnectionTestResult, LLMRequest, LLMResponse, LLMToolCall


class OpenAICompatibleProvider(BaseLLMProvider):
    provider_type = "openai_compatible"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client: httpx.AsyncClient | None = None

    def _require_config(self) -> None:
        if not self.base_url:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 Base URL。", status_code=400)
        if not self.model:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 ID。", status_code=400)
        if not self.api_key:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 API Key。", status_code=400)

    def _get_client(self, timeout_seconds: float) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=timeout_seconds)
        return self._client

    def _endpoint(self) -> str:
        assert self.base_url is not None
        return self.base_url.rstrip("/") + "/chat/completions"

    def _classify_response(self, response: httpx.Response) -> AppError:
        body = redact_text(response.text[:500]) if response.text else ""
        details = {"status_code": response.status_code, "body": body}
        if response.status_code in (401, 403):
            return AppError(
                ErrorCode.LLM_AUTH_FAILED,
                "模型 API 认证失败，请检查 API Key。",
                status_code=502,
                details=details,
            )
        if response.status_code == 404:
            return AppError(
                ErrorCode.LLM_MODEL_NOT_FOUND,
                "模型或接口不存在，请检查 Base URL 与模型 ID。",
                status_code=502,
                details=details,
            )
        if response.status_code == 402:
            return AppError(ErrorCode.LLM_QUOTA_EXCEEDED, "模型账户额度不足。", status_code=502, details=details)
        if response.status_code == 429:
            lowered = body.lower()
            if "quota" in lowered or "insufficient" in lowered:
                return AppError(
                    ErrorCode.LLM_QUOTA_EXCEEDED,
                    "模型账户额度不足或已超出限额。",
                    status_code=502,
                    details=details,
                )
            return AppError(
                ErrorCode.LLM_RATE_LIMITED,
                "模型请求被限流，请稍后再试或降低频率。",
                status_code=502,
                details=details,
                retryable=True,
            )
        if response.status_code >= 500:
            return AppError(
                ErrorCode.LLM_NETWORK_ERROR,
                "模型服务暂时不可用。",
                status_code=502,
                details=details,
                retryable=True,
            )
        lowered = body.lower()
        if "context" in lowered and ("length" in lowered or "token" in lowered):
            return AppError(
                ErrorCode.LLM_INVALID_RESPONSE,
                "上下文超出模型长度限制，请缩短上下文或更换模型。",
                status_code=502,
                details=details,
            )
        return AppError(ErrorCode.LLM_INVALID_RESPONSE, "模型接口返回错误。", status_code=502, details=details)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self._require_config()
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": ([{"role": "system", "content": request.system_prompt}] if request.system_prompt else [])
            + request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        extra_headers = self.config.get("extra_headers")
        if isinstance(extra_headers, dict):
            headers.update({str(k): str(v) for k, v in extra_headers.items()})

        client = self._get_client(request.timeout_seconds or self.timeout_seconds)
        try:
            response = await client.post(self._endpoint(), json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise AppError(
                ErrorCode.LLM_TIMEOUT,
                "模型请求超时。",
                status_code=504,
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise AppError(
                ErrorCode.LLM_NETWORK_ERROR,
                "无法连接模型服务，请检查网络与 Base URL。",
                status_code=502,
                details={"reason": type(exc).__name__},
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                ErrorCode.LLM_NETWORK_ERROR,
                "模型请求发生网络错误。",
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
                "模型返回了无法解析的响应。",
                status_code=502,
            ) from exc

        choices = data.get("choices") or []
        if not choices:
            raise AppError(ErrorCode.LLM_INVALID_RESPONSE, "模型响应缺少 choices。", status_code=502)
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        tool_calls: list[LLMToolCall] = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            raw_args = function.get("arguments")
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
            elif isinstance(raw_args, dict):
                arguments = raw_args
            else:
                arguments = {}
            tool_calls.append(
                LLMToolCall(
                    id=str(call.get("id") or f"call-{index}"),
                    name=str(function.get("name") or ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        usage = data.get("usage") or {}
        return LLMResponse(
            text=str(content) if content else "",
            tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            finish_reason=choices[0].get("finish_reason"),
            request_id=response.headers.get("x-request-id"),
            raw={"model": data.get("model")},
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
            message="模型连接成功。",
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
