"""统一 API 响应包。"""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder

from app.core.context import current_request_id


def ok(data: Any = None, *, request_id: str | None = None) -> dict[str, Any]:
    return {
        "data": jsonable_encoder(data),
        "error": None,
        "request_id": request_id or current_request_id(),
    }


def fail(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": jsonable_encoder(details or {}),
        },
        "request_id": request_id or current_request_id(),
    }
