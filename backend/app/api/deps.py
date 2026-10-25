"""API 依赖：运行时、操作者标识与通用解析。"""

from __future__ import annotations

from typing import Any

from app.runtime import AppRuntime
from fastapi import Request


def get_runtime(request: Request) -> AppRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:  # pragma: no cover - 生命周期保证
        raise RuntimeError("应用运行时尚未初始化。")
    return runtime


def get_actor(request: Request) -> str:
    return "remote-admin" if getattr(request.state, "remote_admin", False) else "local-admin"


def as_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def bool_query(value: str | None) -> bool | None:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return None
