"""OpenAI-compatible Chat Completions Provider（httpx 实现）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx

from app.adapters.llm.base import BaseLLMProvider
from app.adapters.llm.http_utils import (
    RETRY_SAFETY_NONE,
    RETRY_SAFETY_SAFE,
    http_error_details,
    parse_retry_after,
    transport_error,
)
from app.core.errors import AppError, ErrorCode
from app.core.time import iso_utc, utcnow
from app.schemas.llm import LLMModelInfo, LLMRequest, LLMResponse, LLMToolCall, ModelListResult

MAX_MODEL_LIST_ITEMS = 500


class OpenAICompatibleProvider(BaseLLMProvider):
    provider_type = "openai_compatible"
    supports_model_list = True

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

    def _require_model_list_config(self) -> None:
        if not self.base_url:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 Base URL。", status_code=400)
        if not self.api_key:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 API Key。", status_code=400)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # 不跟随重定向，避免 Authorization 被转发到未配置的主机。
            self._client = httpx.AsyncClient(follow_redirects=False)
        return self._client

    def _endpoint(self) -> str:
        assert self.base_url is not None
        return self.base_url.rstrip("/") + "/chat/completions"

    def _models_endpoint(self) -> str:
        assert self.base_url is not None
        return self.base_url.rstrip("/") + "/models"

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        extra_headers = self.config.get("extra_headers")
        if isinstance(extra_headers, dict):
            headers.update({str(k): str(v) for k, v in extra_headers.items()})
        return headers

    def _classify_response(self, response: httpx.Response) -> AppError:
        retry_after = parse_retry_after(response.headers.get("retry-after"))
        lowered = (response.text or "").lower()
        if response.status_code in (401, 403):
            return AppError(
                ErrorCode.LLM_AUTH_FAILED,
                "模型 API 认证失败，请检查 API Key。",
                status_code=502,
                details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
            )
        if response.status_code == 404:
            return AppError(
                ErrorCode.LLM_MODEL_NOT_FOUND,
                "模型或接口不存在，请检查 Base URL 与模型 ID。",
                status_code=502,
                details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
            )
        if response.status_code == 402:
            return AppError(
                ErrorCode.LLM_QUOTA_EXCEEDED,
                "模型账户额度不足。",
                status_code=502,
                details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
            )
        if response.status_code == 429:
            details = http_error_details(
                response,
                retry_safety=RETRY_SAFETY_NONE,
                retry_after_seconds=retry_after,
            )
            if "quota" in lowered or "insufficient" in lowered:
                return AppError(
                    ErrorCode.LLM_QUOTA_EXCEEDED,
                    "模型账户额度不足或已超出限额。",
                    status_code=502,
                    details=details,
                )
            details["retry_safety"] = RETRY_SAFETY_SAFE
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
                details=http_error_details(
                    response,
                    retry_safety=RETRY_SAFETY_SAFE,
                    retry_after_seconds=retry_after,
                ),
                retryable=True,
            )
        if "context" in lowered and ("length" in lowered or "token" in lowered):
            return AppError(
                ErrorCode.LLM_INVALID_RESPONSE,
                "上下文超出模型长度限制，请缩短上下文或更换模型。",
                status_code=502,
                details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
            )
        return AppError(
            ErrorCode.LLM_INVALID_RESPONSE,
            "模型接口返回错误。",
            status_code=502,
            details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
        )

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

        timeout = request.timeout_seconds or self.timeout_seconds
        try:
            response = await self._get_client().post(
                self._endpoint(),
                json=payload,
                headers=self._headers(),
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise transport_error(exc, label="模型") from exc

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

    async def list_models(self, timeout_seconds: float | None = None) -> ModelListResult:
        self._require_model_list_config()
        timeout = timeout_seconds or self.timeout_seconds
        try:
            response = await self._get_client().get(
                self._models_endpoint(),
                headers=self._headers(),
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise transport_error(exc, label="模型") from exc

        if response.status_code in (404, 405, 501):
            return ModelListResult(
                supported=False,
                state="unsupported",
                message="服务商未提供模型列表接口，请手动填写模型 ID。",
                note="404/405/501 被视为不支持模型列表，而不是连通性失败。",
            )
        if response.status_code >= 400:
            raise self._classify_response(response)

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise AppError(
                ErrorCode.LLM_INVALID_RESPONSE,
                "模型列表返回了无法解析的响应。",
                status_code=502,
            ) from exc
        raw_items = data.get("data") if isinstance(data, dict) else data
        if not isinstance(raw_items, list):
            raise AppError(ErrorCode.LLM_INVALID_RESPONSE, "模型列表响应缺少 data 数组。", status_code=502)

        models: list[LLMModelInfo] = []
        seen: set[str] = set()
        truncated = False
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or item.get("name") or "").strip()
            if not model_id or model_id in seen:
                continue
            if len(models) >= MAX_MODEL_LIST_ITEMS:
                truncated = True
                break
            seen.add(model_id)
            models.append(
                LLMModelInfo(
                    id=model_id[:128],
                    display_name=str(item.get("display_name") or item.get("name") or model_id)[:200],
                    created_at=_format_created(item.get("created")),
                    owned_by=str(item.get("owned_by") or "")[:128] or None,
                )
            )
        return ModelListResult(
            supported=True,
            state="available",
            models=models,
            current_model_listed=(self.model in seen) if self.model else None,
            truncated=truncated,
            fetched_at=iso_utc(utcnow()),
            note="模型列表来自服务商实时接口；是否可调用仍以实际生成测试为准。",
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _format_created(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        return value.strip()[:64]
    return None
