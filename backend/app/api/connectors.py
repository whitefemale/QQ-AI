"""连接器管理 API：仅本机回环，所有高风险动作需要输入确认词并写审计。"""

from __future__ import annotations

from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.runtime import AppRuntime
from fastapi import APIRouter, Body, Depends, Query

router = APIRouter()


def _require_confirmation(data: dict[str, Any], expected: str) -> None:
    provided = str(data.get("confirm_text") or "").strip()
    if provided != expected:
        raise AppError(
            ErrorCode.CONNECTOR_CONFIRMATION_REQUIRED,
            f"该操作需要输入确认词「{expected}」；未执行任何动作。",
            status_code=400,
        )


@router.get("/connectors")
async def connector_summary(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.connectors.summary())


@router.get("/connectors/capabilities")
async def connector_capabilities(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.connectors.capabilities())


@router.get("/connectors/installations")
async def list_installations(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    items = await runtime.connectors.list_installations(rescan=True)
    return ok(
        {
            "items": items,
            "note": "只扫描本机配置的连接器根目录；外部安装为只读，不会被自动修改或启动。",
        }
    )


@router.post("/connectors/scan")
async def scan_installations(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    items = await runtime.connectors.scan()
    return ok({"items": items, "count": len(items)})


@router.get("/connectors/installations/{installation_id}")
async def get_installation(
    installation_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.connectors.get_installation(installation_id))


@router.get("/connectors/releases")
async def list_releases(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    items = await runtime.connectors.list_releases()
    return ok(
        {
            "items": items,
            "note": "仅查询官方 Release 元数据，不下载；自动写配置只支持文档化版本。",
        }
    )


@router.get("/connectors/check-release")
async def check_release(
    version: str | None = Query(default=None, max_length=64),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.connectors.check_release(version))


@router.post("/connectors/install")
async def start_install(
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    _require_confirmation(data, "INSTALL")
    version = data.get("version")
    if version is not None and not isinstance(version, str):
        raise AppError(ErrorCode.VALIDATION_ERROR, "版本号必须为字符串。", status_code=400)
    return ok(await runtime.connectors.start_install(version=version, actor=actor))


@router.get("/connectors/jobs/{job_id}")
async def get_job(job_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.connectors.get_job(job_id))


@router.post("/connectors/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    _require_confirmation(data, "CANCEL")
    return ok(await runtime.connectors.cancel_job(job_id, actor=actor))


@router.post("/connectors/installations/{installation_id}/run-installer")
async def run_installer(
    installation_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    _require_confirmation(as_payload(payload), "RUN INSTALLER")
    return ok(await runtime.connectors.run_installer(installation_id, actor=actor))


@router.post("/connectors/installations/{installation_id}/start")
async def start_connector(
    installation_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    _require_confirmation(as_payload(payload), "START NAPCAT")
    return ok(await runtime.connectors.start_connector(installation_id, actor=actor))


@router.post("/connectors/installations/{installation_id}/stop")
async def stop_connector(
    installation_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    _require_confirmation(as_payload(payload), "STOP NAPCAT")
    return ok(await runtime.connectors.stop_connector(installation_id, actor=actor))


@router.get("/connectors/installations/{installation_id}/config/preview")
async def preview_config(
    installation_id: str,
    requested_relative: str | None = Query(default=None, max_length=128),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(
        await runtime.connectors.preview_config(
            installation_id,
            requested_relative=requested_relative,
        )
    )


@router.post("/connectors/installations/{installation_id}/config/apply")
async def apply_config(
    installation_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    _require_confirmation(data, "WRITE CONFIG")
    requested = data.get("requested_relative")
    if requested is not None and not isinstance(requested, str):
        raise AppError(ErrorCode.VALIDATION_ERROR, "配置文件路径必须为字符串。", status_code=400)
    return ok(
        await runtime.connectors.apply_config(
            installation_id,
            requested_relative=requested,
            actor=actor,
        )
    )


@router.get("/connectors/installations/{installation_id}/snapshots")
async def list_snapshots(
    installation_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    items = await runtime.connectors.list_snapshots(installation_id)
    return ok(
        {
            "items": items,
            "note": "快照内容加密保存，接口只返回检查摘要，不返回配置正文或 Token。",
        }
    )


@router.post("/connectors/installations/{installation_id}/config/rollback")
async def rollback_config(
    installation_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    _require_confirmation(data, "RESTORE CONFIG")
    snapshot_group = data.get("snapshot_group")
    if snapshot_group is not None and not isinstance(snapshot_group, str):
        raise AppError(ErrorCode.VALIDATION_ERROR, "快照组标识必须为字符串。", status_code=400)
    return ok(
        await runtime.connectors.rollback_config(
            installation_id,
            snapshot_group=snapshot_group,
            actor=actor,
        )
    )


@router.post("/connectors/installations/{installation_id}/activate")
async def activate_installation(
    installation_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    _require_confirmation(as_payload(payload), "SWITCH VERSION")
    return ok(await runtime.connectors.activate_installation(installation_id, actor=actor))


@router.post("/connectors/installations/{installation_id}/diagnose")
async def diagnose_installation(
    installation_id: str,
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.connectors.diagnose_installation(installation_id, actor=actor))


@router.post("/connectors/accounts/{account_id}/confirm-identity")
async def confirm_identity(
    account_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    _require_confirmation(data, "CONFIRM IDENTITY")
    user_id = data.get("user_id")
    if not isinstance(user_id, str):
        raise AppError(ErrorCode.VALIDATION_ERROR, "请填写当前登录的 QQ 号。", status_code=400)
    return ok(
        await runtime.connectors.confirm_identity(
            account_id,
            user_id=user_id,
            actor=actor,
        )
    )


@router.post("/connectors/import-config")
async def import_config(
    payload: dict[str, Any] | None = Body(default=None),
    actor: str = Depends(get_actor),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    _require_confirmation(data, "IMPORT CONFIG")
    text = data.get("text")
    if not isinstance(text, str):
        raise AppError(ErrorCode.CONNECTOR_IMPORT_INVALID, "请提供配置文件内容。", status_code=400)
    display_name = data.get("display_name")
    if display_name is not None and not isinstance(display_name, str):
        raise AppError(ErrorCode.VALIDATION_ERROR, "显示名称必须为字符串。", status_code=400)
    return ok(
        await runtime.connectors.import_config(
            text=text,
            display_name=display_name,
            actor=actor,
        )
    )


__all__ = ["router"]
