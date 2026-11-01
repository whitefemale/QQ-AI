"""备份恢复集成测试：临时文件 SQLite，不依赖本机数据。"""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.db.session import Database
from app.models.account import Account
from app.models.governance import AuditLog
from app.services.backup_service import BackupService
from app.services.settings_store import get_global_pause, set_global_pause
from sqlalchemy import func, select


class _ManagerStub:
    def __init__(self) -> None:
        self.disconnected: list[str] = []

    async def disconnect_account(self, account_id: str) -> None:
        self.disconnected.append(account_id)


async def test_restore_replaces_database_atomically_and_keeps_global_pause(
    database: Database,
    settings: Settings,
) -> None:
    manager = _ManagerStub()
    service = BackupService(database, settings, manager)  # type: ignore[arg-type]

    async with database.session() as session:
        first = Account(display_name="备份内账号")
        session.add(first)
        await session.commit()
        first_id = first.id

    backup = await service.create_backup(note="恢复测试")

    async with database.session() as session:
        second = Account(display_name="备份后新增账号")
        session.add(second)
        await session.commit()
        second_id = second.id

    await set_global_pause(database, paused=True, reason="恢复测试")
    result = await service.restore_backup(backup["id"], confirm="RESTORE", actor="test")

    assert result["restored"] is True
    assert result["safety_backup"]["id"]
    assert set(manager.disconnected) == {first_id, second_id}

    async with database.session() as session:
        restored_ids = list((await session.execute(select(Account.id))).scalars())
        restored_names = list((await session.execute(select(Account.display_name))).scalars())
    assert restored_ids == [first_id]
    assert restored_names == ["备份内账号"]
    assert second_id not in restored_ids

    pause: dict[str, Any] = await get_global_pause(database)
    assert pause["paused"] is True
    # 暂存文件在原子替换后必须消失，不能残留可能含敏感数据的数据库副本。
    assert list(settings.data_path.glob("*.restore-*")) == []

    backups = await service.list_backups()
    assert {item["id"] for item in backups} >= {backup["id"], result["safety_backup"]["id"]}


@pytest.mark.parametrize("corruption", ["truncated", "same_size_random"])
async def test_corrupted_backup_is_rejected_without_touching_live_database(
    database: Database,
    settings: Settings,
    corruption: str,
) -> None:
    """损坏或截断的备份必须在恢复前被结构化拒绝，不能触碰当前数据库。"""
    manager = _ManagerStub()
    service = BackupService(database, settings, manager)  # type: ignore[arg-type]

    async with database.session() as session:
        session.add(Account(display_name="原始账号"))
        await session.commit()

    backup = await service.create_backup(note="损坏备份测试")
    backup_path = settings.backups_path / backup["filename"]
    original_bytes = backup_path.read_bytes()
    if corruption == "truncated":
        backup_path.write_bytes(original_bytes[: max(1, len(original_bytes) // 3)])
    else:
        backup_path.write_bytes(os.urandom(len(original_bytes)))

    await set_global_pause(database, paused=True, reason="损坏备份恢复测试")
    verification = await service.verify_backup(backup["id"])
    assert verification["checksum_ok"] is False
    assert verification["integrity_ok"] is False
    assert verification["tables"] == {}

    with pytest.raises(AppError) as raised:
        await service.restore_backup(backup["id"], confirm="RESTORE", actor="test")
    assert raised.value.code == ErrorCode.BACKUP_INVALID

    async with database.session() as session:
        accounts = list((await session.execute(select(Account.display_name))).scalars())
        restore_audit = await session.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "backup.restore"))
    assert accounts == ["原始账号"]
    assert restore_audit == 0
    assert manager.disconnected == []
    pause: dict[str, Any] = await get_global_pause(database)
    assert pause["paused"] is True

    backups = await service.list_backups()
    assert {item["id"] for item in backups} == {backup["id"]}
    assert list(settings.data_path.glob("*.restore-*")) == []
