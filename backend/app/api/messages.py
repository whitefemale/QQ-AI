"""消息日志、发送队列、用量与预算。"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime
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
    result["note"] = "已批准为普通敏感度正式记忆；是否注入仍取决于群是否开启长期记忆、记忆是否过期及当前消息相关性。"
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
                "冷却与频率限制",
                "群命令",
                "触发决策（默认仅 @）",
                "上下文与人格提示词",
                "模型调用与工具轮次",
                "回复审查",
                "发送队列与幂等发送",
            ],
            "global_pause": pause,
            "now": iso_utc(utcnow()),
            "note": "任一硬性检查失败都不会发送消息；被拦截原因会记录在消息日志中。",
        }
    )


@router.get("/budgets/{policy_id}")
async def get_budget(policy_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.budgets.get_policy(policy_id))
