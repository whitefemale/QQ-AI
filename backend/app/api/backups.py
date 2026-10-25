"""数据库备份、校验、恢复预览与恢复。"""

from __future__ import annotations

from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime
from app.core.response import ok
from app.runtime import AppRuntime
from fastapi import APIRouter, Body, Depends
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/backups")
async def list_backups(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(
        {
            "items": await runtime.backups.list_backups(),
            "note": "备份只包含 SQLite 数据库，不含媒体文件、日志与加密密钥。",
        }
    )


@router.post("/backups")
async def create_backup(
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    note = str(as_payload(payload).get("note") or "")[:500]
    return ok(await runtime.backups.create_backup(note=note, actor=actor))


@router.get("/backups/{backup_id}")
async def get_backup(backup_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.backups.get_backup(backup_id))


@router.post("/backups/{backup_id}/verify")
async def verify_backup(backup_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.backups.verify_backup(backup_id))


@router.post("/backups/{backup_id}/restore/preview")
async def preview_restore(backup_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.backups.preview_restore(backup_id))


@router.post("/backups/{backup_id}/restore")
async def restore_backup(
    backup_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    confirm = str(as_payload(payload).get("confirm") or "")
    return ok(await runtime.backups.restore_backup(backup_id, confirm=confirm, actor=actor))


@router.delete("/backups/{backup_id}")
async def delete_backup(
    backup_id: str,
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    await runtime.backups.delete_backup(backup_id)
    return ok({"deleted": True, "id": backup_id})


@router.get("/backups/{backup_id}/download")
async def download_backup(backup_id: str, runtime: AppRuntime = Depends(get_runtime)) -> FileResponse:
    filename, path = await runtime.backups.backup_file(backup_id)
    return FileResponse(
        path,
        filename=filename,
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )
