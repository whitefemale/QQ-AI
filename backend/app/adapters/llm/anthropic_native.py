"""Anthropic Messages API 原生 Provider（httpx 实现）。

只使用用户配置的 API Key 与 Base URL；不读取环境中的其他凭证。
请求/响应按官方 Messages API 映射，工具调用转换为 Anthropic tool_use。
"""

from __future__ import annotations

import json
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

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
MAX_MODEL_PAGES = 5
MAX_MODEL_LIST_ITEMS = 500


class AnthropicNativeProvider(BaseLLMProvider):
    provider_type = "anthropic_native"
    supports_model_list = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client: httpx.AsyncClient | None = None

    def _require_config(self) -> None:
        if not self.model:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 ID。", status_code=400)
        if not self.api_key:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 API Key。", status_code=400)

    def _require_model_list_config(self) -> None:
        if not self.api_key:
            raise AppError(ErrorCode.LLM_NOT_CONFIGURED, "尚未配置模型 API Key。", status_code=400)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # 不跟随重定向，避免 x-api-key 被转发到未配置的主机。
            self._client = httpx.AsyncClient(follow_redirects=False)
        return self._client

    def _endpoint(self) -> str:
        base = (self.base_url or DEFAULT_BASE_URL).rstrip("/")
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"

    def _models_endpoint(self) -> str:
        base = (self.base_url or DEFAULT_BASE_URL).rstrip("/")
        if base.endswith("/v1"):
            return base + "/models"
        return base + "/v1/models"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key or "",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _classify_response(self, response: httpx.Response) -> AppError:
        retry_after = parse_retry_after(response.headers.get("retry-after"))
        lowered = (response.text or "").lower()
        if response.status_code in (401, 403):
            return AppError(
                ErrorCode.LLM_AUTH_FAILED,
                "Anthropic API 认证失败，请检查 API Key。",
                status_code=502,
                details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
            )
        if response.status_code == 404:
            return AppError(
                ErrorCode.LLM_MODEL_NOT_FOUND,
                "Anthropic 模型或接口不存在，请检查 Base URL 与模型 ID。",
                status_code=502,
                details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
            )
        if response.status_code == 413 or (response.status_code == 400 and "prompt is too long" in lowered):
            return AppError(
                ErrorCode.LLM_INVALID_RESPONSE,
                "上下文超出 Anthropic 模型长度限制，请缩短上下文或更换模型。",
                status_code=502,
                details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
            )
        if response.status_code == 400 and (
            "credit balance" in lowered or "insufficient" in lowered or "quota" in lowered
        ):
            return AppError(
                ErrorCode.LLM_QUOTA_EXCEEDED,
                "Anthropic 账户额度不足，请检查账单与用量限额。",
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
                    "Anthropic 账户额度不足，请检查账单与用量限额。",
                    status_code=502,
                    details=details,
                )
            details["retry_safety"] = RETRY_SAFETY_SAFE
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
                details=http_error_details(
                    response,
                    retry_safety=RETRY_SAFETY_SAFE,
                    retry_after_seconds=retry_after,
                ),
                retryable=True,
            )
        if response.status_code == 400:
            return AppError(
                ErrorCode.LLM_INVALID_RESPONSE,
                "Anthropic 请求参数无效，请检查模型 ID 与提示词长度。",
                status_code=502,
                details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
            )
        return AppError(
            ErrorCode.LLM_INVALID_RESPONSE,
            "Anthropic 接口返回错误。",
            status_code=502,
            details=http_error_details(response, retry_safety=RETRY_SAFETY_NONE),
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

        timeout = request.timeout_seconds or self.timeout_seconds
        try:
            response = await self._get_client().post(
                self._endpoint(),
                json=payload,
                headers=self._headers(),
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise transport_error(exc, label="Anthropic") from exc

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

    async def list_models(self, timeout_seconds: float | None = None) -> ModelListResult:
        self._require_model_list_config()
        timeout = timeout_seconds or self.timeout_seconds
        models: list[LLMModelInfo] = []
        seen: set[str] = set()
        truncated = False
        after_id: str | None = None
        for page in range(MAX_MODEL_PAGES):
            params: dict[str, Any] = {"limit": 100}
            if after_id:
                params["after_id"] = after_id
            try:
                response = await self._get_client().get(
                    self._models_endpoint(),
                    headers=self._headers(),
                    params=params,
                    timeout=timeout,
                )
            except httpx.HTTPError as exc:
                raise transport_error(exc, label="Anthropic") from exc

            if response.status_code in (404, 405, 501):
                if models:
                    return ModelListResult(
                        supported=False,
                        state="unsupported",
                        models=models,
                        current_model_listed=(self.model in seen) if self.model else None,
                        truncated=True,
                        fetched_at=iso_utc(utcnow()),
                        message="Anthropic 在分页过程中未提供后续模型列表。",
                    )
                return ModelListResult(
                    supported=False,
                    state="unsupported",
                    message="该 Anthropic 端点未提供模型列表接口，请手动填写模型 ID。",
                )
            if response.status_code >= 400:
                raise self._classify_response(response)

            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise AppError(
                    ErrorCode.LLM_INVALID_RESPONSE,
                    "Anthropic 模型列表返回了无法解析的响应。",
                    status_code=502,
                ) from exc
            if not isinstance(data, dict):
                raise AppError(
                    ErrorCode.LLM_INVALID_RESPONSE,
                    "Anthropic 模型列表响应格式无效。",
                    status_code=502,
                )
            items = data.get("data")
            if not isinstance(items, list):
                raise AppError(
                    ErrorCode.LLM_INVALID_RESPONSE,
                    "Anthropic 模型列表响应缺少 data 数组。",
                    status_code=502,
                )
            for item in items:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id") or "").strip()
                if not model_id or model_id in seen:
                    continue
                if len(models) >= MAX_MODEL_LIST_ITEMS:
                    truncated = True
                    break
                seen.add(model_id)
                models.append(
                    LLMModelInfo(
                        id=model_id[:128],
                        display_name=str(item.get("display_name") or model_id)[:200],
                        created_at=str(item.get("created_at") or "")[:64] or None,
                        owned_by=str(item.get("type") or "")[:128] or "anthropic",
                    )
                )
            if truncated:
                break
            has_more = bool(data.get("has_more"))
            last_id = data.get("last_id")
            if not has_more or not isinstance(last_id, str) or not last_id:
                break
            # last_id 必然是刚读取过的模型 ID，不能因为它已在 seen 中而误判分页结束。
            if last_id == after_id:
                break
            after_id = last_id
            if page == MAX_MODEL_PAGES - 1:
                truncated = True
        return ModelListResult(
            supported=True,
            state="available",
            models=models,
            current_model_listed=(self.model in seen) if self.model else None,
            truncated=truncated,
            fetched_at=iso_utc(utcnow()),
            note=("模型列表来自 Anthropic 实时接口；最多读取 5 页/500 条。是否可调用仍以实际生成测试为准。"),
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
