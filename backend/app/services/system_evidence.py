"""接入与诊断共用的证据读取。

原则：
- 实时在线状态只读内存适配器的 ``public_health()``，绝不依赖重启后可能过期的数据库状态。
- 历史测试证据只读取审计白名单字段，不把审计 details、错误消息或标识原样透出。
- GET 接口调用这里的函数时不会写审计、不会建立连接或触发模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select

from app.core.time import ensure_utc, iso_utc, utcnow
from app.db.session import Database
from app.models.account import AdapterInstance
from app.models.governance import AuditLog

FRESH_SECONDS = 3600
AGING_SECONDS = 24 * 3600

CONNECTION_TEST_ACTIONS = ("connector.diagnose", "account.instance.test")
CONNECTION_TEST_INVALIDATORS = ("account.instance.update",)
CONNECTION_TEST_SOURCES = {"live_adapter", "saved_instance_test"}
_VERIFIED_FLAGS = (
    "identity_verified",
    "action_path_verified",
    "group_list_verified",
    "real_inbound_verified",
    "real_outbound_verified",
)


class HealthReader(Protocol):
    async def public_health(self, instance_id: str) -> dict[str, Any] | None: ...


def freshness_state(age_seconds: float | None) -> str:
    """把秒数映射为固定枚举；无时间视为无证据。"""
    if age_seconds is None:
        return "missing"
    if age_seconds <= FRESH_SECONDS:
        return "fresh"
    if age_seconds <= AGING_SECONDS:
        return "aging"
    return "stale"


def freshness_for(timestamp: datetime | None, *, now: datetime | None = None) -> dict[str, Any]:
    current = ensure_utc(now or utcnow())
    value = ensure_utc(timestamp)
    age = max(0, int((current - value).total_seconds())) if value is not None else None
    return {
        "state": freshness_state(age),
        "age_seconds": age,
        "observed_at": iso_utc(value),
    }


def safe_live_facts(health: dict[str, Any] | None) -> dict[str, Any] | None:
    """把适配器健康结果压缩为无标识字段。"""
    if not isinstance(health, dict):
        return None
    return {
        "ok": health.get("ok") is True,
        "status": str(health.get("status") or "unknown")[:32],
        "mode": str(health.get("mode") or health.get("adapter_type") or "unknown")[:32],
        "identity_verified": health.get("identity_verified") is True,
        "observed_at": str(health.get("observed_at") or "")[:64] or None,
    }


async def live_instance_facts(manager: HealthReader, instance_id: str) -> dict[str, Any] | None:
    """读取内存适配器健康状态；不存在时返回 None，不调用任何网络接口。"""
    try:
        return safe_live_facts(await manager.public_health(instance_id))
    except Exception:
        return None


async def latest_audit(
    database: Database,
    *,
    actions: tuple[str, ...],
    target_type: str,
    target_id: str,
) -> AuditLog | None:
    async with database.session() as session:
        return await session.scalar(
            select(AuditLog)
            .where(
                AuditLog.action.in_(actions),
                AuditLog.target_type == target_type,
                AuditLog.target_id == target_id,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        )


async def latest_connection_test(
    database: Database,
    instance: AdapterInstance,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """返回某实例最近一次可归属的连接测试白名单元数据。

    仅接受保存实例自身的测试（``account.instance.test``）或连接器在线诊断
    （``connector.diagnose``）。未保存配置测试 ``account.instance.test_unsaved``
    从来不作为证据；测试之后若实例配置被修改，旧证据立即失效。
    """
    empty: dict[str, Any] = {
        "found": False,
        "invalidated": False,
        "action": None,
        "source": None,
        "ok": False,
        "state": None,
        "tested_at": None,
        "age_seconds": None,
        "freshness": "missing",
        "identity_verified": False,
        "action_path_verified": False,
        "group_list_verified": False,
        "real_inbound_verified": False,
        "real_outbound_verified": False,
        "error_code": None,
        "error_message": None,
    }
    if instance.connection_mode != "onebot11":
        return empty

    evidence = await latest_audit(
        database,
        actions=CONNECTION_TEST_ACTIONS,
        target_type="adapter_instance",
        target_id=instance.id,
    )
    if evidence is None:
        return empty

    updated = await latest_audit(
        database,
        actions=CONNECTION_TEST_INVALIDATORS,
        target_type="adapter_instance",
        target_id=instance.id,
    )
    if updated is not None and ensure_utc(updated.created_at) >= ensure_utc(evidence.created_at):
        return {**empty, "invalidated": True}

    details = evidence.details_json if isinstance(evidence.details_json, dict) else {}
    error_message = details.get("error_message")
    source = details.get("source")
    if source not in CONNECTION_TEST_SOURCES:
        source = "saved_instance_test" if evidence.action == "account.instance.test" else "live_adapter"
    state = details.get("state")
    fresh = freshness_for(evidence.created_at, now=now)
    return {
        "found": True,
        "invalidated": False,
        "action": evidence.action,
        "source": source,
        "ok": details.get("ok") is True,
        "state": state if isinstance(state, str) else None,
        "tested_at": iso_utc(evidence.created_at),
        "age_seconds": fresh["age_seconds"],
        "freshness": fresh["state"],
        "identity_verified": details.get("identity_verified") is True,
        "action_path_verified": details.get("action_path_verified") is True,
        "group_list_verified": details.get("group_list_verified") is True,
        "real_inbound_verified": details.get("real_inbound_verified") is True,
        "real_outbound_verified": details.get("real_outbound_verified") is True,
        "error_code": details.get("error_code") if isinstance(details.get("error_code"), str) else None,
        "error_message": error_message[:300] if isinstance(error_message, str) else None,
    }


__all__ = [
    "AGING_SECONDS",
    "CONNECTION_TEST_ACTIONS",
    "FRESH_SECONDS",
    "freshness_for",
    "freshness_state",
    "latest_audit",
    "latest_connection_test",
    "live_instance_facts",
    "safe_live_facts",
]
