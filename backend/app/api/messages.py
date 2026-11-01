"""消息日志、发送队列、用量与预算。"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime
from app.core.csv import build_csv_bytes
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.core.time import ensure_utc, iso_utc, utcnow
from app.runtime import AppRuntime
from app.services.audit import write_audit
from fastapi import APIRouter, Body, Depends, Query, Request, Response

router = APIRouter()

USAGE_CSV_COLUMNS = [
    "created_at_utc",
    "provider_id",
    "provider_type",
    "model",
    "purpose",
    "group_id",
    "conversation_id",
    "message_id",
    "status",
    "error_code",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "latency_ms",
    "estimated_cost",
    "currency",
    "request_id",
]

MESSAGE_CSV_COLUMNS = [
    "id",
    "platform_message_id",
    "account_id",
    "account_name",
    "group_id",
    "group_name",
    "conversation_id",
    "conversation_type",
    "sender_id",
    "sender_name",
    "is_self",
    "direction",
    "content_text",
    "event_timestamp",
    "processing_status",
    "trigger_reason",
    "model_latency_ms",
    "input_tokens",
    "output_tokens",
    "created_at",
]

MEMORY_CSV_COLUMNS = [
    "id",
    "account_id",
    "group_id",
    "member_id",
    "memory_type",
    "content",
    "sensitivity",
    "confidence",
    "is_pinned",
    "expires_at",
    "source_message_ids",
    "created_at",
    "updated_at",
    "auto_injectable",
]


def _csv_safe(value: Any) -> str:
    """防止表格软件把文本字段当作公式执行；数字与空值保持原样。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


@router.get("/messages")
async def list_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    account_id: str | None = None,
    group_id: str | None = None,
    conversation_id: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    search: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    if direction and direction not in {"inbound", "outbound"}:
        raise AppError(ErrorCode.VALIDATION_ERROR, "direction 必须为 inbound 或 outbound。", status_code=400)
    return ok(
        await runtime.queries.list_messages(
            page=page,
            page_size=page_size,
            account_id=account_id,
            group_id=group_id,
            conversation_id=conversation_id,
            direction=direction,
            status=status,
            search=search,
            since=since,
            until=until,
        )
    )


@router.get("/messages/export.csv")
async def export_messages_csv(
    request: Request,
    account_id: str | None = None,
    group_id: str | None = None,
    conversation_id: str | None = None,
    direction: str | None = None,
    status: str | None = None,
    search: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> Response:
    """导出消息记录；包含消息正文与发送者标识，不含媒体、提示词或任何凭证。"""
    if direction and direction not in {"inbound", "outbound"}:
        raise AppError(ErrorCode.VALIDATION_ERROR, "direction 必须为 inbound 或 outbound。", status_code=400)
    if since is not None and until is not None and ensure_utc(since) > ensure_utc(until):
        raise AppError(ErrorCode.VALIDATION_ERROR, "导出开始时间不能晚于结束时间。", status_code=400)
    rows = await runtime.queries.export_messages(
        account_id=account_id,
        group_id=group_id,
        conversation_id=conversation_id,
        direction=direction,
        status=status,
        search=search,
        since=since,
        until=until,
    )
    content = build_csv_bytes(
        MESSAGE_CSV_COLUMNS,
        [[row.get(column) for column in MESSAGE_CSV_COLUMNS] for row in rows],
    )
    filename = f"messages-{utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    await write_audit(
        runtime.database,
        action="message.export",
        target_type="message",
        details={
            "format": "csv",
            "rows": len(rows),
            "account_id": account_id,
            "group_id": group_id,
            "conversation_id": conversation_id,
            "direction": direction,
            "status": status,
            "since": iso_utc(since),
            "until": iso_utc(until),
            "has_search": bool(search and search.strip()),
        },
        actor=get_actor(request),
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/outbox")
async def list_outbox(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = None,
    group_id: str | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(
        await runtime.queries.list_outbox(
            page=page,
            page_size=page_size,
            status=status,
            group_id=group_id,
        )
    )


@router.post("/outbox/dispatch-due")
async def dispatch_due(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    from app.services.settings_store import get_global_pause

    pause = await get_global_pause(runtime.database)
    if pause.get("paused"):
        raise AppError(
            ErrorCode.GLOBAL_PAUSED,
            "全局紧急暂停中，不会发送任何排队消息。",
            status_code=409,
        )
    processed = await runtime.outbox.send_due(runtime.manager.resolve)
    return ok({"processed": processed, "note": "仅重试明确可重试的失败消息；未知状态不会重发。"})


@router.post("/outbox/{outbox_id}/approve")
async def approve_outbox(
    outbox_id: str,
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    """人工批准待确认回复；可编辑内容，重新审查后立即尝试发送一次。"""
    data = as_payload(payload)
    record = await runtime.outbox.get(outbox_id)
    if record is None:
        raise AppError(ErrorCode.NOT_FOUND, "发送队列消息不存在。", status_code=404)
    adapter = runtime.manager.resolve(record.account_id, record.adapter_instance_id)
    content = data.get("content") if "content" in data else None
    updated = await runtime.outbox.approve(
        outbox_id,
        content=None if content is None else str(content),
        adapter=adapter,
        actor=get_actor(request),
    )
    item = await runtime.queries.get_outbox(updated.id)
    return ok(
        {
            "item": item,
            "sent_immediately": updated.status == "sent",
            "note": (
                "已批准并尝试发送。"
                if updated.status == "sent"
                else "已批准，但当前没有可用连接；消息保留在发送队列，由队列 worker 按正常规则处理。"
            ),
        }
    )


@router.post("/outbox/{outbox_id}/reject")
async def reject_outbox(
    outbox_id: str,
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    updated = await runtime.outbox.reject(
        outbox_id,
        reason=str(data.get("reason") or "") or None,
        actor=get_actor(request),
    )
    item = await runtime.queries.get_outbox(updated.id)
    return ok({"item": item, "status": updated.status})


@router.get("/usage")
async def list_usage(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    provider_id: str | None = None,
    purpose: str | None = None,
    status: str | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(
        await runtime.queries.list_usage(
            page=page,
            page_size=page_size,
            provider_id=provider_id,
            purpose=purpose,
            status=status,
        )
    )


@router.get("/usage/summary")
async def usage_summary(
    hours: int = Query(24, ge=1, le=744),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.budgets.usage_summary(hours=hours))


@router.get("/usage/trends")
async def usage_trends(
    bucket: str = Query("hour", pattern="^(hour|day)$"),
    periods: int = Query(24, ge=1, le=744),
    group_id: str | None = None,
    provider_id: str | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(
        await runtime.budgets.usage_trends(
            bucket=bucket,
            periods=periods,
            group_id=group_id,
            provider_id=provider_id,
        )
    )


@router.get("/usage/export.csv")
async def export_usage_csv(
    request: Request,
    since: datetime | None = None,
    until: datetime | None = None,
    group_id: str | None = None,
    provider_id: str | None = None,
    status: str | None = None,
    purpose: str | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> Response:
    """导出真实模型调用元数据；不包含消息正文、提示词、API Key 或任何凭证。"""
    if since is not None and until is not None and ensure_utc(since) > ensure_utc(until):
        raise AppError(ErrorCode.VALIDATION_ERROR, "导出开始时间不能晚于结束时间。", status_code=400)
    rows = await runtime.queries.export_usage(
        since=since,
        until=until,
        group_id=group_id,
        provider_id=provider_id,
        status=status,
        purpose=purpose,
    )
    buffer = io.StringIO()
    # BOM 便于 Excel 正确识别 UTF-8；CSV 本身仍是标准逗号分隔格式。
    buffer.write("\ufeff")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(USAGE_CSV_COLUMNS)
    for row in rows:
        writer.writerow([_csv_safe(row.get(column)) for column in USAGE_CSV_COLUMNS])
    filename = f"llm-usage-{utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    await write_audit(
        runtime.database,
        action="usage.export",
        target_type="llm_usage",
        details={
            "format": "csv",
            "rows": len(rows),
            "since": iso_utc(since),
            "until": iso_utc(until),
            "group_id": group_id,
            "provider_id": provider_id,
            "status": status,
            "purpose": purpose,
        },
        actor=get_actor(request),
    )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/budgets")
async def list_budgets(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok({"items": await runtime.budgets.list_policies()})


@router.post("/budgets")
async def upsert_budget(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    policy = await runtime.budgets.upsert_policy(as_payload(payload))
    await write_audit(
        runtime.database,
        action="budget.upsert",
        target_type="budget_policy",
        target_id=policy["id"],
        details={key: policy[key] for key in ("scope_type", "scope_id", "window", "metric", "limit_value")},
        actor=get_actor(request),
    )
    return ok(policy)


@router.put("/budgets/{policy_id}")
async def update_budget(
    policy_id: str,
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    policy = await runtime.budgets.upsert_policy(as_payload(payload), policy_id=policy_id)
    await write_audit(
        runtime.database,
        action="budget.update",
        target_type="budget_policy",
        target_id=policy_id,
        actor=get_actor(request),
    )
    return ok(policy)


@router.get("/budgets/check")
async def check_budget(
    group_id: str | None = None,
    provider_id: str | None = None,
    account_id: str | None = None,
    feature: str | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    if feature is not None:
        from app.budgets.service import FEATURE_KEYS, normalize_feature_key

        normalized = normalize_feature_key(feature)
        if normalized not in FEATURE_KEYS:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                f"功能键无效，必须为：{', '.join(sorted(FEATURE_KEYS))}。",
                status_code=400,
            )
        feature = normalized
    check = await runtime.budgets.check(
        group_id=group_id,
        provider_id=provider_id,
        account_id=account_id,
        feature=feature,
    )
    return ok(check.as_dict())


@router.get("/budgets/alerts")
async def list_budget_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    level: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    since: datetime | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(
        await runtime.budgets.list_alerts(
            page=page,
            page_size=page_size,
            level=level,
            scope_type=scope_type,
            scope_id=scope_id,
            since=since,
        )
    )


_MEMORY_NOTE = (
    "仅当群开启长期记忆、记忆未过期、敏感度为 normal，且属于本群或当前发送者时，"
    "相关记忆才会被注入提示词；不会读取其他群的记忆。"
    "AI 提取可由控制台手动触发，也可在群管理中显式开启后台自动提取（增量扫描）；两者都只生成待审核候选。"
)

_CANDIDATE_NOTE = (
    "AI 提取结果只进入待审核候选，批准前不会保存为正式记忆，也不会注入提示词。"
    "提取只读取本群最近入站消息，并排除已标记“排除记忆”的成员；任何聊天内容都不能成为指令。"
    "后台自动提取默认关闭，只生成候选并需人工审核；语义检索仍为规划能力。"
)


@router.get("/memories")
async def list_memories(
    account_id: str | None = None,
    group_id: str | None = None,
    member_id: str | None = None,
    memory_type: str | None = None,
    search: str | None = None,
    include_expired: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    result = await runtime.memories.list_memories(
        account_id=account_id,
        group_id=group_id,
        member_id=member_id,
        memory_type=memory_type,
        search=search,
        include_expired=include_expired,
        page=page,
        page_size=page_size,
    )
    result["note"] = _MEMORY_NOTE
    return ok(result)


@router.post("/memories/extract")
async def extract_memories(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    group_id = str(data.get("group_id") or "").strip()
    if not group_id:
        raise AppError(ErrorCode.VALIDATION_ERROR, "请选择要提取记忆的群。", status_code=400)
    outcome = await runtime.memory_extraction.extract(group_id)
    if outcome is None:  # raise_if_empty 默认为 True，此处仅用于类型收窄。
        raise AppError(ErrorCode.VALIDATION_ERROR, "暂无可提取的消息。", status_code=400)
    result = outcome.as_dict()
    await write_audit(
        runtime.database,
        action="memory.extract",
        target_type="group",
        target_id=group_id,
        details={
            "created_count": result["created_count"],
            "skipped": result["skipped"],
            "provider_id": result["provider_id"],
            "is_mock": result["is_mock"],
        },
        actor=get_actor(request),
    )
    result["note"] = _CANDIDATE_NOTE
    return ok(result)


@router.get("/memories/candidates")
async def list_memory_candidates(
    account_id: str | None = None,
    group_id: str | None = None,
    status: str = "pending",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    result = await runtime.memory_extraction.list_candidates(
        account_id=account_id,
        group_id=group_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    result["note"] = _CANDIDATE_NOTE
    return ok(result)


@router.post("/memories/candidates/{candidate_id}/approve")
async def approve_memory_candidate(
    candidate_id: str,
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    result = await runtime.memory_extraction.approve_candidate(
        candidate_id,
        actor=get_actor(request),
        payload=as_payload(payload),
    )
    await write_audit(
        runtime.database,
        action="memory.candidate.approve",
        target_type="memory_candidate",
        target_id=candidate_id,
        details={
            "memory_id": result["memory"]["id"],
            "is_mock": result["candidate"]["is_mock"],
            "provider_id": result["candidate"]["provider_id"],
        },
        actor=get_actor(request),
    )
    if result["memory"]["sensitivity"] == "sensitive":
        result["note"] = "已批准为敏感记忆；敏感记忆不会自动注入提示词，仅可在控制台查看与管理。"
    else:
        result["note"] = (
            "已批准为普通敏感度正式记忆；是否注入仍取决于群是否开启长期记忆、记忆是否过期及当前消息相关性。"
        )
    return ok(result)


@router.post("/memories/candidates/{candidate_id}/reject")
async def reject_memory_candidate(
    candidate_id: str,
    request: Request,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    result = await runtime.memory_extraction.reject_candidate(candidate_id, actor=get_actor(request))
    await write_audit(
        runtime.database,
        action="memory.candidate.reject",
        target_type="memory_candidate",
        target_id=candidate_id,
        details={"is_mock": result["is_mock"]},
        actor=get_actor(request),
    )
    result["note"] = "候选已拒绝，不会写入正式记忆；记录保留用于审计。"
    return ok(result)


@router.get("/memories/export.csv")
async def export_memories_csv(
    request: Request,
    account_id: str | None = None,
    group_id: str | None = None,
    member_id: str | None = None,
    memory_type: str | None = None,
    search: str | None = None,
    include_expired: bool = True,
    include_sensitive: bool = False,
    runtime: AppRuntime = Depends(get_runtime),
) -> Response:
    """导出记忆 CSV；默认排除 sensitive 记忆，审计不记录正文。"""
    records = await runtime.memories.export_rows(
        account_id=account_id,
        group_id=group_id,
        member_id=member_id,
        memory_type=memory_type,
        search=search,
        include_expired=include_expired,
        include_sensitive=include_sensitive,
    )
    rows = []
    for record in records:
        public = runtime.memories.public(record)
        rows.append(
            [
                public["id"],
                public["account_id"],
                public["group_id"],
                public["member_id"],
                public["memory_type"],
                public["content"],
                public["sensitivity"],
                public["confidence"],
                public["is_pinned"],
                public["expires_at"],
                ";".join(public["source_message_ids"]),
                public["created_at"],
                public["updated_at"],
                public["auto_injectable"],
            ]
        )
    content = build_csv_bytes(MEMORY_CSV_COLUMNS, rows)
    filename = f"memories-{utcnow().strftime('%Y%m%d-%H%M%S')}.csv"
    await write_audit(
        runtime.database,
        action="memory.export",
        target_type="memory",
        details={
            "format": "csv",
            "rows": len(records),
            "include_sensitive": include_sensitive,
            "include_expired": include_expired,
            "account_id": account_id,
            "group_id": group_id,
            "member_id": member_id,
            "memory_type": memory_type,
            "has_search": bool(search and search.strip()),
        },
        actor=get_actor(request),
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Memory-Export-Includes-Sensitive": "true" if include_sensitive else "false",
        },
    )


@router.post("/memories/cleanup")
async def cleanup_memories(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    mode = str(data.get("mode") or "expired")
    days = data.get("days")
    try:
        days_value = None if days is None else int(days)
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.VALIDATION_ERROR, "days 必须是整数。", status_code=400) from exc
    dry_run = bool(data.get("dry_run", False))
    if not dry_run and str(data.get("confirm") or "") != "CLEANUP":
        raise AppError(
            ErrorCode.CONFIRMATION_REQUIRED,
            "真实清理会永久删除记忆，请输入 CLEANUP 以确认。",
            status_code=400,
        )
    result = await runtime.memories.cleanup(
        mode=mode,
        days=days_value,
        dry_run=dry_run,
    )
    await write_audit(
        runtime.database,
        action="memory.cleanup",
        target_type="memory",
        details={
            "mode": result["mode"],
            "days": days,
            "dry_run": dry_run,
            "matched": result["matched"],
            "deleted": result["deleted"],
            "only_unpinned": True,
        },
        actor=get_actor(request),
    )
    result["note"] = "仅统计，未删除任何记忆。" if dry_run else "已删除未固定的匹配记忆；固定记忆不会被清理。"
    return ok(result)


@router.get("/memories/{memory_id}/sources")
async def get_memory_sources(memory_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.memories.sources(memory_id))


@router.get("/memories/{memory_id}")
async def get_memory(memory_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.memories.get_memory(memory_id))


@router.post("/memories")
async def create_memory(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    memory = await runtime.memories.create_memory(as_payload(payload))
    await write_audit(
        runtime.database,
        action="memory.create",
        target_type="memory",
        target_id=memory["id"],
        details={
            "account_id": memory["account_id"],
            "group_id": memory["group_id"],
            "member_id": memory["member_id"],
            "memory_type": memory["memory_type"],
            "manual": True,
        },
        actor=get_actor(request),
    )
    memory["note"] = _MEMORY_NOTE
    return ok(memory)


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    memory = await runtime.memories.update_memory(memory_id, as_payload(payload))
    await write_audit(
        runtime.database,
        action="memory.update",
        target_type="memory",
        target_id=memory_id,
        details={"fields": sorted(as_payload(payload))},
        actor=get_actor(request),
    )
    memory["note"] = _MEMORY_NOTE
    return ok(memory)


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    request: Request,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    await runtime.memories.delete_memory(memory_id)
    await write_audit(
        runtime.database,
        action="memory.delete",
        target_type="memory",
        target_id=memory_id,
        actor=get_actor(request),
    )
    return ok({"deleted": True, "id": memory_id})


@router.get("/policy-explain")
async def policy_explain(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    from app.services.settings_store import get_global_pause

    pause = await get_global_pause(runtime.database)
    return ok(
        {
            "order": [
                "重复事件去重",
                "自身消息过滤",
                "账号与群白名单",
                "全局紧急暂停",
                "群静默时段",
                "成员静音",
                "冷却与频率限制（群级与每人）",
                "群命令",
                "触发决策（新建群默认观察；手动确认模式只入待审队列）",
                "上下文与人格提示词",
                "模型调用与工具轮次",
                "回复审查（敏感内容、长度、空文本）",
                "发送队列与幂等发送（待审核消息绝不自动发送）",
            ],
            "global_pause": pause,
            "now": iso_utc(utcnow()),
            "note": "任一硬性检查失败都不会发送消息；被拦截原因会记录在消息日志中。",
        }
    )


@router.get("/budgets/{policy_id}")
async def get_budget(policy_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.budgets.get_policy(policy_id))
