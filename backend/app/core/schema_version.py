"""Alembic Schema 版本读取与备份兼容性判断。

仅用于比较版本号，不执行迁移、不连接外部服务。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import resolve_backend_root
from app.db.session import Database

BACKEND_ROOT = resolve_backend_root()


async def current_revision(database: Database) -> str | None:
    """读取当前数据库的 Alembic 版本；表不存在或读取失败时返回 None。"""
    try:
        async with database.session() as session:
            result = await session.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
            return str(row[0]) if row and row[0] else None
    except SQLAlchemyError:
        return None


@lru_cache(maxsize=1)
def head_revision() -> str | None:
    """读取代码中的 Alembic head；配置缺失或读取失败时返回 None。"""
    try:
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        head = ScriptDirectory.from_config(config).get_current_head()
        return str(head) if head else None
    except Exception:  # noqa: BLE001 - 版本探测失败不能阻断应用启动
        return None


def schema_compatibility(
    backup_revision: str | None,
    current_revision_value: str | None,
    head_revision_value: str | None,
) -> dict[str, Any]:
    """判断备份 Schema 是否可安全恢复。

    只有备份版本与当前代码 head 都已知且不同时才拒绝；缺少版本信息属于
    unknown，允许恢复但必须显示警告。备份等于 head 时即使当前库版本不同也允许，
    因为恢复后数据库正好是当前程序期望的 Schema。
    """
    common = {
        "backup_revision": backup_revision,
        "current_revision": current_revision_value,
        "head_revision": head_revision_value,
    }
    if not head_revision_value:
        return {
            **common,
            "status": "unknown",
            "compatible": True,
            "restore_allowed": True,
            "message": "无法读取当前程序的 Schema 版本，已允许恢复；请确认备份来源后再操作。",
        }
    if not backup_revision:
        return {
            **common,
            "status": "unknown",
            "compatible": True,
            "restore_allowed": True,
            "message": "备份中没有 Alembic 版本信息，无法核对 Schema；请确认备份来源后再操作。",
        }
    if backup_revision != head_revision_value:
        return {
            **common,
            "status": "incompatible",
            "compatible": False,
            "restore_allowed": False,
            "message": (
                "备份 Schema 版本与当前程序不一致"
                f"（备份 {backup_revision}，当前程序 {head_revision_value}）。"
                "请使用相同版本创建或恢复备份，或先完成升级并重新备份。"
            ),
        }
    return {
        **common,
        "status": "compatible",
        "compatible": True,
        "restore_allowed": True,
        "message": "备份 Schema 版本与当前程序一致。",
    }
