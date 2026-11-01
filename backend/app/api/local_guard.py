"""连接器 API 的本机回环守卫。

即使开启 ``ALLOW_REMOTE_ADMIN``，``/api/connectors`` 也只接受本机回环客户端、
回环 ``Host`` 与（若浏览器发送）回环 ``Origin``。连接器端点能启动固化的本机
程序并写本机配置，不能暴露给远程管理或 DNS rebinding/CSRF。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.core.errors import ErrorCode
from app.core.response import fail
from app.core.security import is_loopback_host
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


def _host_only(value: str | None) -> str | None:
    """从 Host/Origin 中取出主机名；解析失败返回 None。"""
    if not value:
        return None
    text = value.strip()
    if not text or any(ch in text for ch in "\r\n\t "):
        return None
    if "://" in text:
        try:
            return urlsplit(text).hostname
        except ValueError:
            return None
    try:
        return urlsplit(f"//{text}").hostname
    except ValueError:
        return None


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        # 桌面壳、命令行与本机客户端可以不发送 Origin。
        return True
    text = origin.strip()
    if not text:
        return False
    try:
        parsed = urlsplit(text)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return is_loopback_host(parsed.hostname)


class ConnectorLocalGuard(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, prefix: str = "/api") -> None:
        super().__init__(app)
        self.prefix = f"{prefix.rstrip('/')}/connectors"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not (path == self.prefix or path.startswith(f"{self.prefix}/")):
            return await call_next(request)
        client_host = request.client.host if request.client is not None else None
        host = _host_only(request.headers.get("host"))
        if (
            not is_loopback_host(client_host)
            or not is_loopback_host(host)
            or not _origin_allowed(request.headers.get("origin"))
        ):
            return JSONResponse(
                status_code=403,
                content=fail(
                    ErrorCode.CONNECTOR_LOCAL_ONLY,
                    "连接器管理仅允许本机回环访问；远程管理不能操作本机连接器。",
                ),
            )
        return await call_next(request)


__all__ = ["ConnectorLocalGuard"]
