"""系统级接口：健康检查、仪表盘、能力、设置、暂停、审计与 SSE。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.core.time import iso_utc, utcnow
from app.models.governance import AuditLog
from app.runtime import AppRuntime
from app.services.audit import write_audit
from app.services.privacy_service import privacy_overview
from app.services.retention import RETENTION_AUTO_KEY, normalize_retention_days
from app.services.settings_store import (
    get_global_pause,
    list_settings,
    set_global_pause,
    set_setting,
)
from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text

router = APIRouter()


@router.get("/health")
async def health(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(
        {
            "status": "ok",
            "app": runtime.settings.app_name,
            "version": runtime.settings.app_version,
            "env": runtime.settings.app_env,
            "time": iso_utc(utcnow()),
        }
    )


@router.get("/ready")
async def ready(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    try:
        async with runtime.database.session() as session:
            await session.execute(text("SELECT 1"))
        database_ready = True
    except Exception:
        database_ready = False
    pause = await get_global_pause(runtime.database)
    return ok(
        {
            "ready": database_ready,
            "database": "ok" if database_ready else "error",
            "credential_key_configured": runtime.cipher.available,
            "global_paused": bool(pause.get("paused")),
            "event_subscribers": runtime.events.subscriber_count,
            "checked_at": iso_utc(utcnow()),
        }
    )


@router.get("/dashboard")
async def dashboard(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    data = await runtime.dashboard.build()
    data["global_pause"] = await get_global_pause(runtime.database)
    return ok(data)


@router.get("/capabilities")
async def capabilities(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    media = await runtime.providers.capability_overview()
    connections: list[dict[str, Any]] = []
    for mode in runtime.manager.adapter_factory.modes():
        item: dict[str, Any] = {
            "mode": mode["value"],
            "name": mode["label"],
            "state": mode["state"],
            "note": mode["note"],
            "interface": "BaseQQAdapter",
        }
        if mode["value"] == "onebot11":
            item["capabilities"] = {
                "receive": ["text", "mention", "reply", "image", "audio"],
                "send": ["text", "reply", "mention"],
                "media_download": False,
                "note": "当前版本不下载或转存真实图片/语音；AI 只能看到「未配置识别能力」的提示。",
            }
            item["verification"] = {
                "protocol_implemented": True,
                "automated_tests": "local_fake_server",
                "real_qq_verified": False,
                "identity_required_for_online": True,
                "note": "自动化测试只使用本机假服务器；真实 QQ 登录、入站消息与出站发送尚未在本仓库验证。",
            }
        connections.append(item)
    return ok(
        {
            "media": media,
            "llm": {
                "available": ["mock", "openai_compatible", "anthropic_native"],
                "planned": ["official"],
                "note": (
                    "OpenAI-compatible 接口可作为大多数模型服务的通用接入方式；"
                    "Anthropic 原生 Messages API 已可配置，但需要用户提供真实 API Key。"
                ),
            },
            "connections": connections,
            "features": [
                {
                    "key": "long_term_memory",
                    "state": "available",
                    "note": (
                        "支持手动记忆管理与 AI 候选提取（人工审核），并在开启记忆的群内按相关性、"
                        "置信度与固定状态本地检索；仅限本群及当前发送者，绝不跨群。"
                    ),
                },
                {
                    "key": "memory_extraction",
                    "state": "available",
                    "note": (
                        "手动触发模型分析本群最近消息，结果只进入待审核候选；批准前不会保存为正式记忆或注入提示词。"
                    ),
                },
                {
                    "key": "memory_auto_extraction",
                    "state": "available",
                    "note": (
                        "可在群管理中显式开启；后台按增量水位线扫描新消息，只生成待审核候选，"
                        "不会自动批准或注入；全局暂停时停止。批量摘要与冲突合并仍未实现。"
                    ),
                },
                {
                    "key": "memory_semantic_search",
                    "state": "planned",
                    "note": "当前为关键词/二元词匹配，不包含向量语义检索或 Embedding。",
                },
                {
                    "key": "model_routing",
                    "state": "available",
                    "note": (
                        "可按群绑定主模型；未绑定时使用全局默认 Provider。"
                        "当前不支持按功能拆分模型或基于成本/延迟的自动路由。"
                    ),
                },
                {
                    "key": "model_failover",
                    "state": "available",
                    "note": (
                        "主模型发生超时、限流、网络、认证、额度或响应解析等调用错误时，"
                        "可尝试一次显式配置的备用模型；预算、全局暂停、本地凭证缺失/解密失败和配置错误不会触发回退。"
                    ),
                },
                {
                    "key": "usage_breakdown",
                    "state": "available",
                    "note": (
                        "按 Provider 与群聚合本地 llm_usage 记录（请求、成功/失败、Token）；"
                        "未配置单价的调用会标记为不可计价，绝不伪造费用。"
                    ),
                },
                {
                    "key": "cost_estimation",
                    "state": "available",
                    "note": (
                        "仅在你为 Provider 填写输入/输出单价后，按本地 Token 用量估算费用；"
                        "这是本地估算，不是服务商账单。Mock 的外部费用视为 0。"
                    ),
                },
                {
                    "key": "cost_budget",
                    "state": "available",
                    "note": (
                        "可按全局、群或 Provider 设置费用上限并在调用前阻断；"
                        "费用预算要求当前 Provider 已配置单价，未配置时会阻断而不是放行无法计费的调用。"
                    ),
                },
                {
                    "key": "usage_trends",
                    "state": "available",
                    "note": ("按配置时区的小时或自然日聚合真实 llm_usage；未知成本保持为空，不会补成 0。"),
                },
                {
                    "key": "budget_alerts",
                    "state": "available",
                    "note": (
                        "接近预算上限或已超限时生成去重告警事件，并写入审计日志、推送 SSE；事件只反映本地真实用量。"
                    ),
                },
                {
                    "key": "usage_csv_export",
                    "state": "available",
                    "note": (
                        "导出真实模型调用元数据为 CSV；不含消息正文、提示词、API Key 或任何凭证，导出动作写入审计。"
                    ),
                },
                {"key": "real_vision", "state": "unconfigured", "note": "真实视觉 Provider 未配置。"},
                {"key": "real_asr", "state": "unconfigured", "note": "真实语音识别 Provider 未配置。"},
                {
                    "key": "data_retention",
                    "state": "available",
                    "note": (
                        "可按保留天数手动清理消息、媒体与轮转日志，并擦除人格证据与记忆来源。"
                        "自动清理默认关闭，需管理员显式开启；清理不调用模型、不发送消息，日志只删除 app.log.*。"
                    ),
                },
                {
                    "key": "managed_connector_install",
                    "state": "available",
                    "note": (
                        "本机专用连接器页可下载/校验/解压官方包、显式运行安装器、启停受管进程、"
                        "写配置前加密快照与回滚。所有第三方动作需本机确认词；不自动更新/卸载。"
                        "真实安装器、QQ 登录与收发尚未验证。"
                    ),
                },
                {"key": "scheduled_topic", "state": "planned", "note": "定时话题尚未实现。"},
            ],
        }
    )


async def _privacy_overview(runtime: AppRuntime) -> dict[str, Any]:
    return await privacy_overview(runtime.database)


@router.get("/settings")
async def read_settings(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    settings = await list_settings(runtime.database)
    pause = await get_global_pause(runtime.database)
    return ok(
        {
            "runtime": runtime.settings.masked_runtime_info(),
            "app": {
                "name": runtime.settings.app_name,
                "version": runtime.settings.app_version,
                "env": runtime.settings.app_env,
                "api_prefix": runtime.settings.api_prefix,
            },
            "global_pause": pause,
            "retention": normalize_retention_days(settings.get("retention")),
            "retention_status": await runtime.retention.status(),
            "security": {
                "allow_remote_admin": runtime.settings.allow_remote_admin,
                "admin_token_configured": bool(runtime.settings.admin_api_token),
                "credential_key_configured": runtime.cipher.available,
                "cors_origins": runtime.settings.cors_origin_list,
                "allowed_hosts": runtime.settings.allowed_host_list,
            },
            "privacy": await _privacy_overview(runtime),
        }
    )


@router.put("/settings")
async def update_settings(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    actor = get_actor(request)
    changed: list[str] = []
    if "retention" in data:
        raw = data.get("retention")
        if not isinstance(raw, dict):
            raise AppError(ErrorCode.VALIDATION_ERROR, "保留策略格式无效。", status_code=400)
        retention = normalize_retention_days(raw)
        await set_setting(runtime.database, "retention", retention)
        changed.append("retention")
    if "retention_auto" in data:
        raw_auto = data.get("retention_auto")
        if not isinstance(raw_auto, dict) or not isinstance(raw_auto.get("enabled"), bool):
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "自动清理设置格式无效，需提供 enabled 布尔值。",
                status_code=400,
            )
        await runtime.retention.set_enabled(bool(raw_auto["enabled"]), actor=actor)
        changed.append(RETENTION_AUTO_KEY)
    if "global_pause" in data:
        raw_pause = data.get("global_pause")
        if not isinstance(raw_pause, dict):
            raise AppError(ErrorCode.VALIDATION_ERROR, "全局暂停设置格式无效。", status_code=400)
        paused = bool(raw_pause.get("paused"))
        await set_global_pause(
            runtime.database,
            paused=paused,
            reason=str(raw_pause.get("reason") or "")[:500],
            actor=actor,
        )
        changed.append("global_pause")
    if not changed:
        raise AppError(ErrorCode.VALIDATION_ERROR, "没有可更新的设置项。", status_code=400)
    await write_audit(
        runtime.database,
        action="settings.update",
        target_type="system_settings",
        details={"changed_fields": changed},
        actor=actor,
    )
    return await read_settings(runtime)


@router.get("/system/retention/status")
async def retention_status(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.retention.status())


@router.get("/system/retention/preview")
async def retention_preview(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    """只读统计；不删除数据、不写审计、不更新上次运行记录。"""
    return ok(await runtime.retention.preview())


@router.post("/system/retention/run")
async def retention_run(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    confirm = str(as_payload(payload).get("confirm") or "")
    summary = await runtime.retention.run(trigger="manual", actor=get_actor(request), confirm=confirm)
    return ok(summary)


@router.post("/system/pause-all")
async def pause_all(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    reason = str(as_payload(payload).get("reason") or "管理员手动暂停")[:500]
    pause = await set_global_pause(runtime.database, paused=True, reason=reason, actor=get_actor(request))
    await write_audit(
        runtime.database,
        action="system.pause_all",
        target_type="system",
        details={"reason": reason},
        actor=get_actor(request),
    )
    runtime.events.publish("system.paused", {"reason": reason})
    return ok({"global_pause": pause, "note": "全局暂停立即生效；后台发送队列将停止发送。"})


@router.post("/system/resume")
async def resume_all(
    request: Request,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    pause = await set_global_pause(runtime.database, paused=False, actor=get_actor(request))
    await write_audit(
        runtime.database,
        action="system.resume",
        target_type="system",
        actor=get_actor(request),
    )
    runtime.events.publish("system.resumed", {})
    return ok({"global_pause": pause, "note": "已恢复；请确认群配置与配额后再允许自动回复。"})


@router.get("/audit")
async def list_audit(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    conditions: list[Any] = []
    if action:
        conditions.append(AuditLog.action.ilike(f"%{action.strip()[:100]}%"))
    if target_type:
        conditions.append(AuditLog.target_type == target_type)
    if target_id:
        conditions.append(AuditLog.target_id == target_id)
    offset = (page - 1) * page_size
    async with runtime.database.session() as session:
        total = await session.scalar(select(func.count(AuditLog.id)).where(*conditions))
        records = list(
            (
                await session.execute(
                    select(AuditLog)
                    .where(*conditions)
                    .order_by(AuditLog.created_at.desc())
                    .offset(offset)
                    .limit(page_size)
                )
            ).scalars()
        )
    return ok(
        {
            "items": [
                {
                    "id": record.id,
                    "actor": record.actor,
                    "action": record.action,
                    "target_type": record.target_type,
                    "target_id": record.target_id,
                    "details": record.details_json,
                    "request_id": record.request_id,
                    "ip_address": record.ip_address,
                    "created_at": iso_utc(record.created_at),
                }
                for record in records
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/events/recent")
async def recent_events(
    limit: int = Query(20, ge=1, le=100),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok({"items": runtime.events.recent(limit=limit)})


def _sse(event: dict[str, Any]) -> str:
    return f"id: {event.get('seq')}\nevent: {event.get('type')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("/events/stream")
async def event_stream(
    request: Request,
    replay: int = Query(0, ge=0, le=50),
    runtime: AppRuntime = Depends(get_runtime),
) -> StreamingResponse:
    async def generator():
        yield ": connected\n\n"
        for item in reversed(runtime.events.recent(limit=replay)):
            yield _sse(item)
        async with runtime.events.subscribe() as queue:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                except asyncio.CancelledError:
                    break
                yield _sse(event)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
