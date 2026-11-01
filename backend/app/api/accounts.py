"""QQ 账号与连接器管理。"""

from __future__ import annotations

from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime, require_confirmation
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.runtime import AppRuntime
from app.services.settings_store import get_global_pause
from fastapi import APIRouter, Body, Depends, Query, Request

router = APIRouter()


@router.get("/accounts")
async def list_accounts(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(
        {
            "items": await runtime.accounts.list_accounts(),
            # 由适配器工厂注册表派生，新增适配器无需在此手写分支。
            "connection_modes": runtime.manager.adapter_factory.modes(),
            "global_pause": await get_global_pause(runtime.database),
        }
    )


@router.post("/accounts")
async def create_account(
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.accounts.create_account(as_payload(payload)))


@router.post("/accounts/test-connection")
async def test_unsaved_connection(
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.accounts.test_unsaved_connection(as_payload(payload)))


@router.get("/accounts/{account_id}")
async def get_account(account_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.accounts.get_account(account_id))


@router.patch("/accounts/{account_id}")
async def update_account(
    account_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.accounts.update_account(account_id, as_payload(payload)))


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: str,
    request: Request,
    confirm: str | None = Query(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    require_confirmation(confirm, "DELETE", "删除账号会永久删除其群、消息、记忆与发送队列，请输入 DELETE 以确认。")
    await runtime.accounts.delete_account(account_id, actor=get_actor(request))
    return ok({"deleted": True, "id": account_id})


@router.post("/accounts/{account_id}/instances")
async def add_instance(
    account_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.accounts.add_instance(account_id, as_payload(payload)))


@router.patch("/accounts/{account_id}/instances/{instance_id}")
async def update_instance(
    account_id: str,
    instance_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.accounts.update_instance(account_id, instance_id, as_payload(payload)))


@router.delete("/accounts/{account_id}/instances/{instance_id}")
async def delete_instance(
    account_id: str,
    instance_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    await runtime.accounts.delete_instance(account_id, instance_id)
    return ok({"deleted": True, "id": instance_id})


@router.post("/accounts/{account_id}/instances/{instance_id}/connect")
async def connect_instance(
    account_id: str,
    instance_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.accounts.connect_instance(account_id, instance_id))


@router.post("/accounts/{account_id}/instances/{instance_id}/disconnect")
async def disconnect_instance(
    account_id: str,
    instance_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.accounts.disconnect_instance(account_id, instance_id))


@router.post("/accounts/{account_id}/instances/{instance_id}/test")
async def test_saved_instance(
    account_id: str,
    instance_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(
        await runtime.accounts.test_saved_instance(
            account_id,
            instance_id,
            as_payload(payload),
        )
    )


@router.get("/accounts/{account_id}/instances/{instance_id}/groups")
async def fetch_connector_groups(
    account_id: str,
    instance_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.accounts.fetch_connector_groups(account_id, instance_id))


@router.get("/accounts/{account_id}/status")
async def account_status(account_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    account = await runtime.accounts.get_account(account_id)
    return ok(
        {
            "account": account,
            "global_pause": await get_global_pause(runtime.database),
            "note": "状态来自进程内实时适配器；重启后需重新连接。",
        }
    )


@router.post("/accounts/{account_id}/mock/events")
async def inject_mock_event(
    account_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    if not data.get("text") and not data.get("segments"):
        raise AppError(ErrorCode.VALIDATION_ERROR, "模拟消息不能为空。", status_code=400)
    return ok(await runtime.playground.inject_mock_event(account_id, data))


@router.get("/accounts/{account_id}/mock/sent")
async def list_mock_sent(
    account_id: str,
    limit: int = Query(20, ge=1, le=100),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    account = await runtime.accounts.get_account(account_id)
    items: list[dict[str, Any]] = []
    for instance in account.get("instances", []):
        adapter = runtime.manager.get_adapter(instance["id"])
        if adapter is None:
            continue
        for message in getattr(adapter, "sent_messages", [])[-limit:]:
            items.append(message.model_dump(mode="json"))
    return ok({"items": items[-limit:], "note": "仅显示当前进程内 Mock 连接器的已发送消息。"})
