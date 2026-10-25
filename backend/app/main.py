"""FastAPI 应用入口：生命周期、迁移、鉴权边界、统一响应与静态前端托管。"""

from __future__ import annotations

import asyncio
import hmac
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.api import accounts, backups, demo, extensions, groups, messages, personas, playground, providers, system
from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.core.context import request_id_var
from app.core.errors import AppError, ErrorCode
from app.core.logging import setup_logging
from app.core.response import fail, ok
from app.core.security import is_loopback_host, redact_value
from app.runtime import AppRuntime

logger = logging.getLogger(__name__)

BACKEND_ROOT = PROJECT_ROOT / "backend"
_LOCAL_HOSTS = {"testclient", "testserver"}


def run_migrations(settings: Settings) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_sync_url.replace("%", "%%"))
    config.attributes["settings"] = settings
    command.upgrade(config, "head")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request_id = "".join(ch for ch in request_id if ch.isalnum() or ch in "-_")[:64] or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response


class RemoteAdminGuard(BaseHTTPMiddleware):
    """管理 API 默认只接受本机请求；远程访问必须显式启用并携带管理 Token。"""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings
        self.prefix = settings.api_prefix.rstrip("/") or "/api"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not (path == self.prefix or path.startswith(f"{self.prefix}/")):
            return await call_next(request)
        client_host = request.client.host if request.client is not None else None
        if is_loopback_host(client_host) or client_host in _LOCAL_HOSTS:
            request.state.remote_admin = False
            return await call_next(request)
        if not self.settings.allow_remote_admin:
            return JSONResponse(
                status_code=403,
                content=fail(
                    ErrorCode.REMOTE_ADMIN_FORBIDDEN,
                    "默认只允许本机管理。远程访问需显式开启 ALLOW_REMOTE_ADMIN 并配置管理 Token。",
                ),
            )
        expected = self.settings.admin_api_token.strip()
        provided = request.headers.get("X-Admin-Token") or ""
        if not provided:
            authorization = request.headers.get("Authorization") or ""
            if authorization.lower().startswith("bearer "):
                provided = authorization[7:].strip()
        if not expected or not provided or not hmac.compare_digest(expected, provided):
            return JSONResponse(
                status_code=401,
                content=fail(ErrorCode.UNAUTHORIZED, "远程管理 Token 缺失或不正确。"),
            )
        request.state.remote_admin = True
        return await call_next(request)


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "业务错误",
            extra={"error_code": exc.code, "event": "api.error"},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(exc.code, exc.message, details=redact_value(exc.details)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "loc": [str(part) for part in error.get("loc", [])],
                "message": str(error.get("msg", ""))[:200],
                "type": str(error.get("type", ""))[:80],
            }
            for error in exc.errors()[:20]
        ]
        return JSONResponse(
            status_code=422,
            content=fail(
                ErrorCode.VALIDATION_ERROR,
                "请求参数不合法。",
                details={"fields": fields},
            ),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) and exc.detail else "请求无法完成。"
        code = {
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            405: "METHOD_NOT_ALLOWED",
            409: ErrorCode.CONFLICT,
            429: "RATE_LIMITED",
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.VALIDATION_ERROR)
        return JSONResponse(status_code=exc.status_code, content=fail(code, message, details={}))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理的服务端异常")
        return JSONResponse(
            status_code=500,
            content=fail(ErrorCode.INTERNAL_ERROR, "服务器内部错误，请查看本地日志。"),
        )


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = settings.frontend_dist_path
    assets = dist / "assets"
    if assets.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    base = dist.resolve()

    @app.get("/", include_in_schema=False)
    async def root() -> Any:
        index = base / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            status_code=200,
            content=ok(
                {
                    "message": (
                        "后端已启动。前端尚未构建，开发模式请运行 Vite；或执行 npm run build 生成 frontend/dist。"
                    ),
                    "docs": f"{settings.api_prefix}/docs",
                }
            ),
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> Any:
        if full_path == "api" or full_path.startswith("api/") or full_path.startswith("openapi"):
            raise HTTPException(status_code=404, detail="接口不存在。")
        candidate = (base / full_path).resolve()
        if candidate.is_file() and (candidate == base or base in candidate.parents):
            return FileResponse(candidate)
        index = base / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="前端尚未构建。")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 目录必须在日志初始化之前创建，否则全新安装时日志文件无法打开。
        settings.ensure_directories()
        setup_logging(settings.log_level, log_file=settings.logs_path / "app.log")
        if settings.auto_migrate:
            await asyncio.to_thread(run_migrations, settings)
        runtime = AppRuntime(settings)
        await runtime.start()
        app.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.stop()
            app.state.runtime = None

    app = FastAPI(
        title=f"{settings.app_name} 管理 API",
        version=settings.app_version,
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(RemoteAdminGuard, settings=settings)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Admin-Token", "X-Request-ID", "Last-Event-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    prefix = settings.api_prefix.rstrip("/") or "/api"
    for module in (
        system,
        accounts,
        groups,
        personas,
        providers,
        messages,
        extensions,
        playground,
        backups,
        demo,
    ):
        app.include_router(module.router, prefix=prefix)

    _register_error_handlers(app)
    _mount_frontend(app, settings)
    return app


app = create_app()

__all__ = ["app", "create_app", "run_migrations"]
