"""人格工作台：模式、模板、成长、特征、版本与回滚。"""

from __future__ import annotations

from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime, require_confirmation
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.models.persona import DEFAULT_PERSONA_THRESHOLDS
from app.runtime import AppRuntime
from app.services.persona_service import PERSONA_MODE_LABELS, PERSONA_TEMPLATES
from fastapi import APIRouter, Body, Depends, Query

router = APIRouter()


@router.get("/personas")
async def list_personas(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(
        {
            "items": await runtime.personas.list_personas(),
            "modes": [{"value": key, "label": label} for key, label in PERSONA_MODE_LABELS.items()],
            "thresholds_default": DEFAULT_PERSONA_THRESHOLDS,
            "growth_policies": [
                {"value": "auto", "label": "自动应用", "note": "通过治理校验后直接生成新版本。"},
                {"value": "review", "label": "人工审核", "note": "提案进入待审核队列，由管理员批准。"},
                {"value": "paused", "label": "暂停成长", "note": "不进行任何自动成长分析。"},
            ],
            "learning_scopes": [
                {"value": "admin_only", "label": "仅控制台手动触发"},
                {"value": "group", "label": "仅当前群"},
                {"value": "cross_group", "label": "跨群学习（默认关闭，不推荐）"},
            ],
        }
    )


@router.get("/personas/templates")
async def list_templates() -> dict[str, Any]:
    return ok(
        {
            "items": [
                {
                    "key": key,
                    "name": data["name"],
                    "description": data["description"],
                    "self_description": data["self_description"],
                }
                for key, data in PERSONA_TEMPLATES.items()
            ]
        }
    )


@router.post("/personas")
async def create_persona(
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    return ok(await runtime.personas.create_persona(as_payload(payload), actor=actor))


@router.get("/personas/growth/pending")
async def list_pending_all(
    persona_id: str | None = Query(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok({"items": await runtime.growth.list_pending(persona_id)})


@router.post("/personas/growth/{event_id}/review")
async def review_growth(
    event_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    data = as_payload(payload)
    if "approve" not in data:
        raise AppError(ErrorCode.VALIDATION_ERROR, "请明确选择批准或拒绝该提案。", status_code=400)
    outcome = await runtime.growth.review(event_id, approve=bool(data.get("approve")), actor=actor)
    return ok(outcome.as_dict())


@router.post("/personas/evidence/{message_id}/delete")
async def delete_evidence(
    message_id: str,
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    return ok(await runtime.personas.delete_evidence(message_id, actor=actor))


@router.get("/personas/traits/{trait_id}")
async def get_trait(trait_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    async with runtime.database.session() as session:
        from app.models.persona import PersonaTrait
        from app.services.persona_store import trait_public

        trait = await session.get(PersonaTrait, trait_id)
        if trait is None:
            raise AppError(ErrorCode.NOT_FOUND, "人格特征不存在。", status_code=404)
        return ok(trait_public(trait))


@router.patch("/personas/traits/{trait_id}")
async def update_trait(
    trait_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    data = as_payload(payload)
    result: dict[str, Any] | None = None
    if "status" in data:
        result = await runtime.personas.set_trait_status(trait_id, str(data.get("status") or ""), actor=actor)
    if "locked" in data:
        result = await runtime.personas.set_trait_locked(trait_id, bool(data.get("locked")), actor=actor)
    if result is None:
        raise AppError(ErrorCode.VALIDATION_ERROR, "请提供 status 或 locked。", status_code=400)
    return ok(result)


@router.delete("/personas/traits/{trait_id}")
async def delete_trait(
    trait_id: str,
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    await runtime.personas.delete_trait(trait_id, actor=actor)
    return ok({"deleted": True, "id": trait_id})


@router.post("/personas/{persona_id}/test")
async def test_persona(
    persona_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    if not data.get("account_id") or not data.get("group_id"):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "测试人格请选择账号与一个已登记的群（用于读取该群的规则与配置）。",
            status_code=400,
        )
    data["persona_id"] = persona_id
    return ok(await runtime.playground.run_dry(data))


@router.get("/personas/{persona_id}")
async def get_persona(persona_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.personas.detail(persona_id))


@router.post("/personas/{persona_id}/preview")
async def preview_persona_update(
    persona_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.personas.preview_update(persona_id, as_payload(payload)))


@router.patch("/personas/{persona_id}")
async def update_persona(
    persona_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    return ok(await runtime.personas.update_persona(persona_id, as_payload(payload), actor=actor))


@router.delete("/personas/{persona_id}")
async def delete_persona(
    persona_id: str,
    confirm: str | None = Query(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    require_confirmation(
        confirm,
        "DELETE",
        "删除人格会同时删除其版本与成长记录，且不可恢复；请输入 DELETE 以确认。",
    )
    await runtime.personas.delete_persona(persona_id, actor=actor)
    return ok({"deleted": True, "id": persona_id})


@router.get("/personas/{persona_id}/traits")
async def list_traits(
    persona_id: str,
    status: str | None = Query(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    await runtime.personas.get_persona(persona_id)
    return ok({"items": await runtime.personas.list_traits(persona_id, status=status)})


@router.post("/personas/{persona_id}/growth/analyze")
async def analyze_growth(
    persona_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    data = as_payload(payload)
    outcome = await runtime.growth.analyze(
        persona_id,
        group_id=str(data.get("group_id") or "") or None,
        trigger="manual",
        actor=actor,
    )
    return ok(outcome.as_dict())


@router.get("/personas/{persona_id}/growth/pending")
async def list_pending(
    persona_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok({"items": await runtime.growth.list_pending(persona_id)})


@router.get("/personas/{persona_id}/events")
async def list_events(
    persona_id: str,
    limit: int = Query(50, ge=1, le=200),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    await runtime.personas.get_persona(persona_id)
    return ok({"items": await runtime.personas.list_events(persona_id, limit=limit)})


@router.get("/personas/{persona_id}/events/{event_id}/evidence")
async def get_event_evidence(
    persona_id: str,
    event_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.personas.event_evidence(persona_id, event_id))


@router.get("/personas/{persona_id}/versions")
async def list_versions(
    persona_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    await runtime.personas.get_persona(persona_id)
    return ok({"items": await runtime.personas.list_versions(persona_id)})


@router.get("/personas/{persona_id}/versions/{version_id}")
async def get_version(
    persona_id: str,
    version_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.personas.version_detail(persona_id, version_id))


@router.post("/personas/{persona_id}/versions/{version_id}/restore")
async def restore_version(
    persona_id: str,
    version_id: str,
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    return ok(await runtime.personas.rollback(persona_id, version_id, actor=actor))


@router.post("/personas/{persona_id}/reset")
async def reset_persona(
    persona_id: str,
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    return ok(await runtime.personas.reset(persona_id, actor=actor))
