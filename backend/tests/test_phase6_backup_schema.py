"""阶段 6：备份 Schema 兼容门禁、恢复预览与删除审计。"""

from __future__ import annotations

from typing import Any

import pytest
from app.core.config import Settings
from app.core.errors import AppError
from app.core.schema_version import schema_compatibility
from app.db.session import Database
from app.main import create_app
from app.models.account import Account
from app.models.governance import AuditLog
from app.services.backup_service import BackupService
from app.services.settings_store import set_global_pause
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text


class _ManagerStub:
    def __init__(self) -> None:
        self.disconnected: list[str] = []

    async def disconnect_account(self, account_id: str) -> None:
        self.disconnected.append(account_id)


def _data(response: Any) -> Any:
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["error"] is None, body
    return body["data"]


@pytest.mark.parametrize(
    ("backup", "current", "head", "status", "allowed"),
    [
        ("abc", "abc", "abc", "compatible", True),
        ("abc", "def", "abc", "compatible", True),
        ("abc", "abc", "def", "incompatible", False),
        (None, "abc", "abc", "unknown", True),
        ("abc", "abc", None, "unknown", True),
    ],
)
def test_schema_compatibility_branches(
    backup: str | None,
    current: str | None,
    head: str | None,
    status: str,
    allowed: bool,
) -> None:
    result = schema_compatibility(backup, current, head)
    assert result["status"] == status
    assert result["restore_allowed"] is allowed
    assert result["compatible"] is allowed
    assert result["backup_revision"] == backup
    assert result["current_revision"] == current
    assert result["head_revision"] == head
    assert result["message"]


async def _set_alembic_revision(database: Database, revision: str) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await connection.execute(text("DELETE FROM alembic_version"))
        await connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": revision},
        )


async def _add_account(database: Database, name: str) -> str:
    async with database.session() as session:
        account = Account(display_name=name)
        session.add(account)
        await session.commit()
        await session.refresh(account)
        return account.id


async def test_preview_marks_create_all_database_as_unknown(
    database: Database,
    settings: Settings,
) -> None:
    service = BackupService(database, settings, _ManagerStub())  # type: ignore[arg-type]
    backup = await service.create_backup(note="无 Alembic 版本")

    preview = await service.preview_restore(backup["id"])

    assert backup["schema_version"] is None
    assert preview["schema"]["status"] == "unknown"
    assert preview["schema"]["restore_allowed"] is True
    assert preview["app_version"] == {"backup": settings.app_version, "current": settings.app_version}
    assert any("没有 Alembic 版本信息" in warning for warning in preview["warnings"])


async def test_preview_reports_compatible_schema_and_app_version(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _set_alembic_revision(database, "rev-head")
    monkeypatch.setattr("app.services.backup_service.head_revision", lambda: "rev-head")
    service = BackupService(database, settings, _ManagerStub())  # type: ignore[arg-type]
    backup = await service.create_backup(note="Schema 预览")

    preview = await service.preview_restore(backup["id"])

    assert preview["schema"] == {
        "backup_revision": "rev-head",
        "current_revision": "rev-head",
        "head_revision": "rev-head",
        "status": "compatible",
        "compatible": True,
        "restore_allowed": True,
        "message": "备份 Schema 版本与当前程序一致。",
    }
    assert preview["app_version"] == {"backup": settings.app_version, "current": settings.app_version}
    assert preview["verification"]["schema_version"] == "rev-head"
    assert preview["requires_pause"] is True
    assert preview["confirm_phrase"] == "RESTORE"


async def test_restore_rejects_incompatible_schema_without_safety_backup(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _set_alembic_revision(database, "rev-old")
    service = BackupService(database, settings, _ManagerStub())  # type: ignore[arg-type]
    kept_id = await _add_account(database, "备份内账号")
    backup = await service.create_backup(note="旧 Schema")

    after_backup_id = await _add_account(database, "备份后新增账号")
    await set_global_pause(database, paused=True, reason="Schema 测试")
    monkeypatch.setattr("app.services.backup_service.head_revision", lambda: "rev-new")

    before_backups = len(await service.list_backups())
    with pytest.raises(AppError) as excinfo:
        await service.restore_backup(backup["id"], confirm="RESTORE", actor="schema-tester")

    assert excinfo.value.code == "BACKUP_SCHEMA_INCOMPATIBLE"
    assert excinfo.value.status_code == 409
    assert excinfo.value.details == {
        "backup_schema": "rev-old",
        "current_schema": "rev-old",
        "head_schema": "rev-new",
    }
    assert len(await service.list_backups()) == before_backups
    async with database.session() as session:
        ids = set((await session.execute(select(Account.id))).scalars())
        restore_audits = int(
            await session.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "backup.restore")) or 0
        )
    assert ids == {kept_id, after_backup_id}
    assert restore_audits == 0


async def test_restore_accepts_compatible_schema_and_audits_versions(
    database: Database,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _set_alembic_revision(database, "rev-head")
    monkeypatch.setattr("app.services.backup_service.head_revision", lambda: "rev-head")
    service = BackupService(database, settings, _ManagerStub())  # type: ignore[arg-type]
    kept_id = await _add_account(database, "备份内账号")
    backup = await service.create_backup(note="兼容 Schema")
    after_backup_id = await _add_account(database, "备份后新增账号")
    await set_global_pause(database, paused=True, reason="Schema 测试")

    result = await service.restore_backup(backup["id"], confirm="RESTORE", actor="schema-tester")

    assert result["restored"] is True
    async with database.session() as session:
        ids = list((await session.execute(select(Account.id))).scalars())
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "backup.restore").order_by(AuditLog.created_at.desc())
        )
    assert ids == [kept_id]
    assert after_backup_id not in ids
    assert audit is not None and audit.actor == "schema-tester"
    details = dict(audit.details_json or {})
    assert details["verified_schema"] == "rev-head"
    assert details["schema_status"] == "compatible"
    assert details["backup_schema"] == "rev-head"
    assert details["current_schema"] == "rev-head"
    assert details["head_schema"] == "rev-head"
    assert details["backup_app_version"] == settings.app_version
    assert details["current_app_version"] == settings.app_version


def test_delete_backup_requires_confirm_and_writes_audit(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        backup = _data(client.post("/api/backups", json={"note": "删除测试"}))

        missing = client.delete(f"/api/backups/{backup['id']}")
        assert missing.status_code == 400
        assert missing.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
        _data(client.get(f"/api/backups/{backup['id']}"))

        _data(client.delete(f"/api/backups/{backup['id']}", params={"confirm": "DELETE"}))
        assert client.get(f"/api/backups/{backup['id']}").status_code == 404

        audit = _data(client.get("/api/audit", params={"action": "backup.delete"}))
        assert audit["total"] == 1
        item = audit["items"][0]
        assert item["actor"] == "local-admin"
        assert item["target_id"] == backup["id"]
        assert item["details"] == {"filename": backup["filename"]}
