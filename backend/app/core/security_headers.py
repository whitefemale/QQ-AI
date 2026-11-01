"""统一安全响应头与 HTML CSP。

以纯 ASGI 中间件实现，避免缓冲流式响应；只对 HTML 添加 CSP。
Swagger 文档页依赖 CDN 与内联脚本，单独豁免 CSP。
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP_EXEMPT_PATHS = {"/api/docs", "/api/docs/oauth2-redirect"}

CSP_HTML = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    )
)

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), usb=(), serial=(), clipboard-read=(), clipboard-write=(self)"
    ),
}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in BASE_HEADERS.items():
                    headers.setdefault(name, value)
                content_type = headers.get("content-type", "")
                if path not in CSP_EXEMPT_PATHS and content_type.startswith("text/html"):
                    headers.setdefault("Content-Security-Policy", CSP_HTML)
            await send(message)

        await self.app(scope, receive, send_with_headers)
