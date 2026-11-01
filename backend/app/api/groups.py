"""群白名单、回复模式、限速与成员状态。"""

from __future__ import annotations

from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime, require_confirmation
from app.core.response import ok
from app.pipeline.policy import DEFAULT_RATE_LIMITS
from app.runtime import AppRuntime
from fastapi import APIRouter, Body, Depends, Query, Request

router = APIRouter()


@router.get("/groups")
async def list_groups(
    account_id: str | None = Query(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    items = await runtime.groups.list_groups()
    if account_id:
        items = [item for item in items if item["account_id"] == account_id]
    return ok(
        {
            "items": items,
            "reply_modes": [
                {
                    "value": "observe",
                    "label": "观察（默认）",
                    "note": "只记录消息和做安全判断，不生成回复；新建与导入的群默认使用此模式。",
                },
                {
                    "value": "mention_only",
                    "label": "仅 @ 回复",
                    "note": "仅在群成员 @ AI，或回复 AI 消息时生成回复。",
                },
                {
                    "value": "manual_confirm",
                    "label": "手动确认",
                    "note": "触发条件与仅 @ 相同，但回复只进入待确认队列，绝不自动发送。",
                },
                {
                    "value": "always",
                    "label": "自动回复",
                    "note": "对所有通过硬规则的消息生成回复，仍受预算、频率与输出审查限制。",
                },
                {
                    "value": "keyword",
                    "label": "关键词触发（高级）",
                    "note": "命中关键词，或被 @ / 回复 AI 消息时生成回复。",
                },
                {
                    "value": "context",
                    "label": "上下文参与",
                    "state": "planned",
                    "note": "规划中，当前版本保存时会被拒绝；可用「仅 @ 回复」或「关键词触发」。",
                },
                {
                    "value": "scheduled",
                    "label": "定时话题",
                    "state": "planned",
                    "note": "规划中，当前不可用。",
                },
            ],
            "rate_limit_defaults": DEFAULT_RATE_LIMITS,
            "note": ("群默认不启用；白名单为空时不会回复任何群。新建/导入群默认观察，已有群不会被自动改写回复模式。"),
            "llm_routing_note": (
                "主/备用模型为可选的群级绑定；未绑定时使用全局默认 Provider。"
                "备用模型仅在主模型发生可回退的调用错误时尝试一次，不会绕过预算、暂停或权限限制。"
            ),
        }
    )


@router.post("/groups")
async def create_group(
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.groups.create_group(as_payload(payload)))


@router.get("/groups/members")
async def list_members(
    account_id: str | None = Query(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok({"items": await runtime.groups.list_members(account_id)})


@router.post("/groups/import")
async def import_groups(
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    account_id = str(data.get("account_id") or "")
    groups = data.get("groups")
    if not isinstance(groups, list):
        groups = []
    return ok(await runtime.groups.import_groups(account_id, groups))


@router.post("/groups/import-connector")
async def import_connector_groups(
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    account_id = str(data.get("account_id") or "")
    instance_id = str(data.get("instance_id") or "")
    confirmed = data.get("confirm_self_user_id")
    if confirmed is not None and not isinstance(confirmed, str):
        confirmed = ""
    await runtime.accounts.require_confirmed_identity(account_id, instance_id, confirmed)
    fetched = await runtime.accounts.fetch_connector_groups(account_id, instance_id)
    result = await runtime.groups.import_groups(account_id, fetched["groups"])
    result["fetched_at"] = fetched["fetched_at"]
    result["note"] = "新导入的群默认关闭 AI 回复且为观察模式；已有群保留原配置，请逐群确认后再启用。"
    return ok(result)


@router.get("/groups/{group_id}")
async def get_group(group_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.groups.get_group(group_id))


@router.patch("/groups/{group_id}")
async def update_group(
    group_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.groups.update_group(group_id, as_payload(payload)))


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: str,
    request: Request,
    confirm: str | None = Query(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    require_confirmation(
        confirm,
        "DELETE",
        "删除群会删除群配置与记忆，并取消待发送消息；历史消息会保留但不再关联该群。请输入 DELETE 以确认。",
    )
    await runtime.groups.delete_group(group_id, actor=get_actor(request))
    return ok({"deleted": True, "id": group_id})


@router.post("/groups/{group_id}/pause")
async def pause_group(group_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.groups.set_paused(group_id, True))


@router.post("/groups/{group_id}/resume")
async def resume_group(group_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.groups.set_paused(group_id, False))
