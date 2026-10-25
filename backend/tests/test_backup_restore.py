"""备份恢复集成测试：临时文件 SQLite，不依赖本机数据。"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.db.session import Database
from app.models.account import Account
from app.services.backup_service import BackupService
from app.services.settings_store import get_global_pause, set_global_pause
from sqlalchemy import select


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
