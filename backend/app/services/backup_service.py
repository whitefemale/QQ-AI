"""SQLite 一致性备份、校验与恢复。

- 备份只包含数据库，不包含媒体文件、日志或明文密钥。
- 数据库中的 Token / API Key 始终是 Fernet 密文；恢复后需保留同一加密密钥。
- 恢复是高危操作：必须全局暂停、断开所有连接器，并显式二次确认。
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.time import iso_utc, utcnow
from app.db.session import Database
from app.models.account import Account
from app.models.governance import BackupRecord
from app.services.adapter_manager import AdapterManager
from app.services.audit import write_audit
from app.services.settings_store import get_global_pause, set_global_pause

_KEY_TABLES = (
    "accounts",
    "groups",
    "messages",
    "outbox_messages",
    "personas",
    "persona_traits",
    "llm_providers",
    "llm_usage",
    "audit_logs",
    "system_settings",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_path(database_sync_url: str) -> Path:
    url = make_url(database_sync_url)
    if not url.database:
        raise AppError(ErrorCode.BACKUP_INVALID, "当前数据库不是可备份的 SQLite 文件。", status_code=500)
    return Path(url.database)


def _backup_database(source: Path, target: Path) -> None:
    source_conn = sqlite3.connect(str(source), timeout=30)
    target_conn = sqlite3.connect(str(target), timeout=30)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _remove_with_retry(path: Path, *, attempts: int = 20, delay: float = 0.1) -> None:
    """Windows 上刚关闭的 SQLite 连接可能短暂占用文件，重试释放 WAL/SHM。"""
    for attempt in range(attempts):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _replace_with_retry(source: Path, target: Path, *, attempts: int = 20, delay: float = 0.1) -> None:
    """在目标同目录内原子替换；失败时保留原数据库，避免半截覆盖。"""
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _table_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(str(path))
    try:
        existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts: dict[str, int] = {}
        for table in _KEY_TABLES:
            if table in existing:
                counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return counts
    finally:
        connection.close()


def _schema_version(path: Path) -> str | None:
    connection = sqlite3.connect(str(path))
    try:
        rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        return str(rows[0][0]) if rows else None
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def _integrity_check(path: Path) -> tuple[bool, str]:
    connection = sqlite3.connect(str(path))
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        value = str(result[0]) if result else "unknown"
        return value.lower() == "ok", value
    except sqlite3.Error as exc:
        return False, f"数据库无法读取：{type(exc).__name__}"
    finally:
        connection.close()


def _verify(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise AppError(ErrorCode.BACKUP_NOT_FOUND, "备份文件不存在。", status_code=404)
    actual = _sha256(path)
    sha_ok = expected_sha256 is None or actual == expected_sha256
    integrity_ok, integrity_message = _integrity_check(path)
    return {
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": actual,
        "checksum_ok": sha_ok,
        "integrity_ok": integrity_ok,
        "integrity_message": integrity_message,
        "schema_version": _schema_version(path),
        "tables": _table_counts(path),
        "verified_at": iso_utc(utcnow()),
    }


class BackupService:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        manager: AdapterManager,
    ) -> None:
        self.database = database
        self.settings = settings
        self.manager = manager
        self.backups_path = settings.backups_path
        self.database_path = _sqlite_path(settings.database_sync_url)

    def _record_public(self, record: BackupRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "filename": record.filename,
            "sha256": record.sha256,
            "size_bytes": record.size_bytes,
            "manifest": dict(record.manifest_json or {}),
            "app_version": record.app_version,
            "schema_version": record.schema_version,
            "status": record.status,
            "includes_secrets": record.includes_secrets,
            "created_at": iso_utc(record.created_at),
            "download_path": f"/api/backups/{record.id}/download",
        }

    async def _record_by_id(self, backup_id: str) -> BackupRecord:
        async with self.database.session() as session:
            record = await session.get(BackupRecord, backup_id)
        if record is None:
            raise AppError(ErrorCode.BACKUP_NOT_FOUND, "备份记录不存在。", status_code=404)
        return record

    def _path_for(self, record: BackupRecord) -> Path:
        path = (self.backups_path / record.filename).resolve()
        if path.parent != self.backups_path.resolve():
            raise AppError(ErrorCode.BACKUP_INVALID, "备份文件路径无效。", status_code=400)
        return path

    async def list_backups(self) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            records = list(
                (await session.execute(select(BackupRecord).order_by(BackupRecord.created_at.desc()))).scalars()
            )
        return [self._record_public(record) for record in records]

    async def get_backup(self, backup_id: str) -> dict[str, Any]:
        return self._record_public(await self._record_by_id(backup_id))

    async def create_backup(self, *, note: str = "", actor: str = "local-admin") -> dict[str, Any]:
        self.backups_path.mkdir(parents=True, exist_ok=True)
        if not self.database_path.exists():
            raise AppError(ErrorCode.BACKUP_INVALID, "数据库文件不存在，无法备份。", status_code=500)
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"backup-{stamp}-{uuid.uuid4().hex[:6]}.db"
        target = self.backups_path / filename
        await asyncio.to_thread(_backup_database, self.database_path, target)
        sha256 = await asyncio.to_thread(_sha256, target)
        counts = await asyncio.to_thread(_table_counts, target)
        schema_version = await asyncio.to_thread(_schema_version, target)
        integrity_ok, integrity_message = await asyncio.to_thread(_integrity_check, target)
        if not integrity_ok:
            target.unlink(missing_ok=True)
            raise AppError(
                ErrorCode.BACKUP_INVALID,
                f"备份完整性校验失败：{integrity_message}",
                status_code=500,
            )
        manifest = {
            "format": "ai-group-friend-sqlite-backup",
            "format_version": 1,
            "created_at": iso_utc(utcnow()),
            "note": note[:500],
            "app_version": self.settings.app_version,
            "schema_version": schema_version,
            "scope": "database_only",
            "includes_plaintext_secrets": False,
            "includes_media": False,
            "tables": counts,
            "credential_note": (
                "Token 与 API Key 以 Fernet 密文存储，恢复后必须保留同一 CREDENTIAL_ENCRYPTION_KEY "
                "才能解密；加密密钥本身不包含在备份中。"
            ),
        }
        async with self.database.session() as session:
            record = BackupRecord(
                filename=filename,
                sha256=sha256,
                size_bytes=target.stat().st_size,
                manifest_json=manifest,
                app_version=self.settings.app_version,
                schema_version=schema_version,
                status="created",
                includes_secrets=False,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            public = self._record_public(record)
            backup_id = record.id
        await write_audit(
            self.database,
            action="backup.create",
            target_type="backup",
            target_id=backup_id,
            details={"filename": filename, "tables": manifest["tables"]},
            actor=actor,
        )
        return public

    async def verify_backup(self, backup_id: str) -> dict[str, Any]:
        record = await self._record_by_id(backup_id)
        path = self._path_for(record)
        result = await asyncio.to_thread(_verify, path, record.sha256)
        if result["checksum_ok"] and result["integrity_ok"]:
            async with self.database.session() as session:
                current = await session.get(BackupRecord, backup_id)
                if current is not None:
                    current.status = "verified"
                    await session.commit()
        return result

    async def preview_restore(self, backup_id: str) -> dict[str, Any]:
        verification = await self.verify_backup(backup_id)
        record = await self._record_by_id(backup_id)
        pause = await get_global_pause(self.database)
        async with self.database.session() as session:
            accounts = await session.scalar(select(func.count(Account.id)))
        return {
            "backup": self._record_public(record),
            "verification": verification,
            "current_state": {"accounts": int(accounts or 0)},
            "requires_pause": True,
            "paused": bool(pause.get("paused")),
            "confirm_phrase": "RESTORE",
            "warnings": [
                "恢复会用备份中的数据库覆盖当前数据库。",
                "恢复前会自动创建一份安全备份。",
                "恢复会断开所有 QQ 连接器，所有账号需重新连接。",
                "媒体文件、日志不包含在备份中。",
                "加密密钥不在备份中；密钥变化后旧凭证将无法解密。",
            ],
        }

    async def restore_backup(
        self,
        backup_id: str,
        *,
        confirm: str,
        actor: str = "local-admin",
    ) -> dict[str, Any]:
        if confirm != "RESTORE":
            raise AppError(
                ErrorCode.BACKUP_INVALID,
                "请输入 RESTORE 以确认恢复操作。",
                status_code=400,
            )
        pause = await get_global_pause(self.database)
        if not pause.get("paused"):
            raise AppError(
                ErrorCode.BACKUP_RESTORE_REQUIRES_PAUSE,
                "恢复前必须先在系统设置中启用全局紧急暂停。",
                status_code=409,
            )
        record = await self._record_by_id(backup_id)
        verification = await self.verify_backup(backup_id)
        if not verification["checksum_ok"] or not verification["integrity_ok"]:
            raise AppError(ErrorCode.BACKUP_INVALID, "备份校验未通过，已拒绝恢复。", status_code=400)
        path = self._path_for(record)

        safety = await self.create_backup(note=f"恢复 {record.filename} 前的自动安全备份", actor="system")

        async with self.database.session() as session:
            accounts = list((await session.execute(select(Account))).scalars())
        for account in accounts:
            await self.manager.disconnect_account(account.id)

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        wal = Path(f"{self.database_path}-wal")
        shm = Path(f"{self.database_path}-shm")
        # 先复制到同目录暂存文件，再原子替换；避免复制中途失败把当前库截断。
        staging = self.database_path.with_name(f"{self.database_path.name}.restore-{uuid.uuid4().hex[:8]}")
        await self.database.dispose()
        try:
            await asyncio.to_thread(shutil.copyfile, path, staging)
            await asyncio.to_thread(_remove_with_retry, wal)
            await asyncio.to_thread(_remove_with_retry, shm)
            await asyncio.to_thread(_replace_with_retry, staging, self.database_path)
        except Exception as exc:
            await asyncio.to_thread(staging.unlink, missing_ok=True)
            raise AppError(
                ErrorCode.BACKUP_INVALID,
                "恢复数据库文件失败，请使用安全备份手动恢复。",
                status_code=500,
                details={"safety_backup_id": safety["id"], "reason": type(exc).__name__},
            ) from exc
        integrity_ok, integrity_message = await asyncio.to_thread(_integrity_check, self.database_path)
        if not integrity_ok:
            raise AppError(
                ErrorCode.BACKUP_INVALID,
                f"恢复后的数据库校验失败：{integrity_message}。安全备份 ID：{safety['id']}",
                status_code=500,
            )
        try:
            # 备份可能是在未暂停时创建的；恢复后强制保持暂停，避免立即发送。
            await set_global_pause(
                self.database,
                paused=True,
                reason=f"已从备份 {record.filename} 恢复，请人工确认后手动解除暂停。",
                actor=actor,
            )
        except Exception as exc:
            raise AppError(
                ErrorCode.BACKUP_INVALID,
                "数据库已恢复，但写入全局暂停状态失败，请立即手动暂停并检查。",
                status_code=500,
                details={"safety_backup_id": safety["id"], "reason": type(exc).__name__},
            ) from exc
        await self._ensure_record(safety)
        await self._ensure_record(
            {
                "id": record.id,
                "filename": record.filename,
                "sha256": record.sha256,
                "size_bytes": record.size_bytes,
                "manifest": record.manifest_json,
                "app_version": record.app_version,
                "schema_version": record.schema_version,
                "status": "restored",
                "includes_secrets": record.includes_secrets,
            }
        )
        await write_audit(
            self.database,
            action="backup.restore",
            target_type="backup",
            target_id=backup_id,
            details={
                "filename": record.filename,
                "safety_backup_id": safety["id"],
                "verified_schema": verification["schema_version"],
            },
            actor=actor,
        )
        return {
            "restored": True,
            "backup_id": backup_id,
            "safety_backup": safety,
            "verification": verification,
            "restored_at": iso_utc(utcnow()),
            "next_steps": [
                "所有连接器已断开；请确认群配置后重新连接。",
                "全局暂停仍处于启用状态，确认无误后请手动恢复。",
                "如使用不同的 CREDENTIAL_ENCRYPTION_KEY，请恢复原密钥后再使用已有 Token / API Key。",
            ],
        }

    async def delete_backup(self, backup_id: str) -> None:
        record = await self._record_by_id(backup_id)
        path = self._path_for(record)
        path.unlink(missing_ok=True)
        async with self.database.session() as session:
            current = await session.get(BackupRecord, backup_id)
            if current is not None:
                await session.delete(current)
                await session.commit()
        await write_audit(
            self.database,
            action="backup.delete",
            target_type="backup",
            target_id=backup_id,
            details={"filename": record.filename},
        )

    async def backup_file(self, backup_id: str) -> tuple[str, Path]:
        record = await self._record_by_id(backup_id)
        path = self._path_for(record)
        if not path.exists():
            raise AppError(ErrorCode.BACKUP_NOT_FOUND, "备份文件不存在。", status_code=404)
        return record.filename, path

    async def _ensure_record(self, data: dict[str, Any]) -> None:
        backup_id = str(data.get("id") or "")
        if not backup_id:
            return
        async with self.database.session() as session:
            if await session.get(BackupRecord, backup_id) is not None:
                return
            session.add(
                BackupRecord(
                    id=backup_id,
                    filename=str(data["filename"]),
                    sha256=str(data["sha256"]),
                    size_bytes=int(data["size_bytes"]),
                    manifest_json=dict(data.get("manifest") or {}),
                    app_version=str(data.get("app_version") or ""),
                    schema_version=data.get("schema_version"),
                    status=str(data.get("status") or "created"),
                    includes_secrets=bool(data.get("includes_secrets")),
                )
            )
            await session.commit()
