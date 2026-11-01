"""LLM HTTP 适配器共用的重试与错误元数据工具。

这些函数只处理协议层面的元数据，不读取或记录请求头中的凭证。
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.errors import AppError, ErrorCode
from app.core.security import redact_text
from app.core.time import utcnow

RETRY_SAFETY_SAFE = "safe"
RETRY_SAFETY_AMBIGUOUS = "ambiguous"
RETRY_SAFETY_NONE = "none"


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """解析 Retry-After（秒数或 HTTP 日期），失败返回 None。

    只返回非负秒数；调用方负责设置等待上限。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        current = now or utcnow()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return max(0.0, (parsed - current).total_seconds())
    if math.isnan(seconds) or math.isinf(seconds) or seconds < 0:
        return None
    return seconds


def upstream_request_id(response: httpx.Response) -> str | None:
    for header in ("x-request-id", "request-id", "x-amzn-requestid"):
        value = response.headers.get(header)
        if value:
            return value[:128]
    return None


def http_error_details(
    response: httpx.Response,
    *,
    retry_safety: str,
    retry_after_seconds: float | None = None,
) -> dict[str, Any]:
    body = redact_text(response.text[:500]) if response.text else ""
    details: dict[str, Any] = {
        "status_code": response.status_code,
        "body": body,
        "retry_safety": retry_safety,
    }
    request_id = upstream_request_id(response)
    if request_id:
        details["upstream_request_id"] = request_id
    if retry_after_seconds is not None:
        details["retry_after_seconds"] = round(retry_after_seconds, 3)
    return details


def transport_error(exc: Exception, *, label: str) -> AppError:
    """把 httpx 传输异常转换为稳定的 AppError，并标记重试安全性。

    - 连接建立失败 / 连接池等待超时：请求没有到达服务端，可安全重试。
    - 读写超时、协议中断：服务端可能已经生成并计费，默认视为 ambiguous 不自动重试。
    """
    if isinstance(exc, (httpx.ConnectTimeout, httpx.PoolTimeout)):
        return AppError(
            ErrorCode.LLM_TIMEOUT,
            f"{label}连接超时。",
            status_code=504,
            details={"reason": type(exc).__name__, "retry_safety": RETRY_SAFETY_SAFE},
            retryable=True,
        )
    if isinstance(exc, httpx.TimeoutException):
        return AppError(
            ErrorCode.LLM_TIMEOUT,
            f"{label}请求超时。",
            status_code=504,
            details={"reason": type(exc).__name__, "retry_safety": RETRY_SAFETY_AMBIGUOUS},
            retryable=True,
        )
    if isinstance(exc, httpx.ConnectError):
        return AppError(
            ErrorCode.LLM_NETWORK_ERROR,
            f"无法连接{label}服务，请检查网络与 Base URL。",
            status_code=502,
            details={"reason": type(exc).__name__, "retry_safety": RETRY_SAFETY_SAFE},
            retryable=True,
        )
    if isinstance(
        exc,
        (
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.DecodingError,
        ),
    ):
        return AppError(
            ErrorCode.LLM_NETWORK_ERROR,
            f"{label}连接在响应完成前中断。",
            status_code=502,
            details={"reason": type(exc).__name__, "retry_safety": RETRY_SAFETY_AMBIGUOUS},
            retryable=True,
        )
    if isinstance(exc, httpx.TransportError):
        return AppError(
            ErrorCode.LLM_NETWORK_ERROR,
            f"{label}请求发生网络错误。",
            status_code=502,
            details={"reason": type(exc).__name__, "retry_safety": RETRY_SAFETY_AMBIGUOUS},
            retryable=True,
        )
    return AppError(
        ErrorCode.LLM_NETWORK_ERROR,
        f"{label}请求发生未知网络错误。",
        status_code=502,
        details={"reason": type(exc).__name__, "retry_safety": RETRY_SAFETY_NONE},
        retryable=False,
    )
