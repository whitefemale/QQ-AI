"""群白名单、回复模式、限速与成员状态。"""

from __future__ import annotations

from typing import Any

from app.api.deps import as_payload, get_runtime
from app.core.response import ok
from app.pipeline.policy import DEFAULT_RATE_LIMITS
from app.runtime import AppRuntime
from fastapi import APIRouter, Body, Depends, Query

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
                    "label": "仅观察",
                    "note": "记录消息但不回复，适合先观察群氛围。",
                },
                {"value": "mention_only", "label": "仅 @ 回复（推荐）", "note": "默认模式，最保守。"},
                {"value": "keyword", "label": "关键词触发", "note": "命中关键词时回复。"},
                {"value": "context", "label": "上下文参与", "note": "较主动，仍受频率与连续回复限制。"},
                {
                    "value": "scheduled",
                    "label": "定时话题",
                    "state": "planned",
                    "note": "规划中，当前不可用。",
                },
            ],
            "rate_limit_defaults": DEFAULT_RATE_LIMITS,
            "note": "群默认不启用；白名单为空时不会回复任何群。",
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
    fetched = await runtime.accounts.fetch_connector_groups(account_id, instance_id)
    result = await runtime.groups.import_groups(account_id, fetched["groups"])
    result["fetched_at"] = fetched["fetched_at"]
    result["note"] = "导入的群默认关闭 AI 回复；请逐群确认后再启用。"
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
async def delete_group(group_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    await runtime.groups.delete_group(group_id)
    return ok({"deleted": True, "id": group_id})


@router.post("/groups/{group_id}/pause")
async def pause_group(group_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.groups.set_paused(group_id, True))


@router.post("/groups/{group_id}/resume")
async def resume_group(group_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.groups.set_paused(group_id, False))
