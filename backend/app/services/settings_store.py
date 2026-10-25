"""系统级设置的持久化（全局暂停等）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.models.governance import SystemSetting

GLOBAL_PAUSE_KEY = "global_pause"


async def get_setting(database: Database, key: str, default: Any = None) -> Any:
    async with database.session() as session:
        record = await session.get(SystemSetting, key)
        if record is None:
            return default
        return record.value_json


async def set_setting(database: Database, key: str, value: Any) -> dict[str, Any]:
    async with database.session() as session:
        record = await session.get(SystemSetting, key)
        if record is None:
            record = SystemSetting(key=key, value_json=value, updated_at=utcnow())
            session.add(record)
        else:
            record.value_json = value
            record.updated_at = utcnow()
        await session.commit()
    return value


async def get_global_pause(database: Database) -> dict[str, Any]:
    value = await get_setting(database, GLOBAL_PAUSE_KEY, default=None)
    if not isinstance(value, dict):
        return {"paused": False, "reason": "", "updated_at": None, "actor": None}
    return {
        "paused": bool(value.get("paused")),
        "reason": str(value.get("reason") or ""),
        "updated_at": value.get("updated_at"),
        "actor": value.get("actor"),
    }


async def set_global_pause(
    database: Database,
    *,
    paused: bool,
    reason: str = "",
    actor: str = "local-admin",
) -> dict[str, Any]:
    value = {
        "paused": paused,
        "reason": reason if paused else "",
        "updated_at": iso_utc(utcnow()),
        "actor": actor,
    }
    await set_setting(database, GLOBAL_PAUSE_KEY, value)
    return value


async def list_settings(database: Database) -> dict[str, Any]:
    async with database.session() as session:
        result = await session.execute(select(SystemSetting).order_by(SystemSetting.key))
        records = list(result.scalars())
    return {record.key: record.value_json for record in records}
