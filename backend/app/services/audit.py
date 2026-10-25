"""管理操作审计。所有管理端写操作都应记录，details 自动脱敏。"""

from __future__ import annotations

import logging
from typing import Any

from app.core.context import current_request_id
from app.core.security import redact_value
from app.db.session import Database
from app.models.governance import AuditLog

logger = logging.getLogger(__name__)

_MAX_DETAILS_SIZE = 4000


def _safe_details(details: dict[str, Any] | None) -> dict[str, Any]:
    redacted = redact_value(details or {})
    if not isinstance(redacted, dict):
        return {"value": redacted}
    if len(str(redacted)) > _MAX_DETAILS_SIZE:
        return {"note": "审计详情过大，已省略部分内容。"}
    return redacted


async def write_audit(
    database: Database,
    *,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    actor: str = "local-admin",
    ip_address: str | None = None,
) -> None:
    try:
        async with database.session() as session:
            session.add(
                AuditLog(
                    actor=actor,
                    action=action,
                    target_type=target_type,
                    target_id=str(target_id) if target_id is not None else None,
                    details_json=_safe_details(details),
                    request_id=current_request_id(),
                    ip_address=ip_address,
                )
            )
            await session.commit()
    except Exception:  # 审计失败不能阻断业务，但必须留下日志
        logger.exception("写入审计日志失败", extra={"action": action, "target_id": target_id})
