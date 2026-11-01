"""模型 Provider 与媒体能力 Provider。"""

from __future__ import annotations

from typing import Any

from app.api.deps import as_payload, get_actor, get_runtime
from app.core.errors import AppError, ErrorCode
from app.core.response import ok
from app.runtime import AppRuntime
from app.services.audit import write_audit
from fastapi import APIRouter, Body, Depends, Query

router = APIRouter()

MAX_TEST_PROMPT = 2000


def _operation_id(data: dict[str, Any]) -> str | None:
    value = data.get("operation_id")
    if value is None:
        return None
    if not isinstance(value, str):
        raise AppError(ErrorCode.VALIDATION_ERROR, "operation_id 必须为字符串。", status_code=400)
    return value


def _prompt(data: dict[str, Any], *, required: bool) -> str | None:
    value = data.get("prompt")
    if value is None:
        if required:
            raise AppError(ErrorCode.VALIDATION_ERROR, "请填写测试提示词。", status_code=400)
        return None
    if not isinstance(value, str):
        raise AppError(ErrorCode.VALIDATION_ERROR, "提示词必须为字符串。", status_code=400)
    text = value.strip()
    if required and not text:
        raise AppError(ErrorCode.VALIDATION_ERROR, "请填写测试提示词。", status_code=400)
    if len(text) > MAX_TEST_PROMPT:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"测试提示词不能超过 {MAX_TEST_PROMPT} 个字符。",
            status_code=400,
        )
    if any(ch < " " and ch not in "\n\t" for ch in text) or "\x7f" in text:
        raise AppError(ErrorCode.VALIDATION_ERROR, "提示词不能包含控制字符。", status_code=400)
    return text or None


def _int_field(data: dict[str, Any], key: str, minimum: int, maximum: int) -> int | None:
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise AppError(ErrorCode.VALIDATION_ERROR, f"{key} 必须为整数。", status_code=400)
    if value < minimum or value > maximum:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            f"{key} 必须在 {minimum}–{maximum} 之间。",
            status_code=400,
        )
    return value


def _temperature(data: dict[str, Any]) -> float | None:
    if "temperature" not in data or data["temperature"] is None:
        return None
    value = data["temperature"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AppError(ErrorCode.VALIDATION_ERROR, "temperature 必须为数字。", status_code=400)
    if not 0.0 <= float(value) <= 2.0:
        raise AppError(ErrorCode.VALIDATION_ERROR, "temperature 必须在 0–2 之间。", status_code=400)
    return float(value)


@router.get("/providers")
async def list_providers(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(
        {
            "items": await runtime.providers.list_llm_providers(),
            "types": [
                {
                    "value": "mock",
                    "label": "Mock 模型（演示）",
                    "available": True,
                    "note": "固定模板回复，仅用于流程测试。",
                },
                {
                    "value": "openai_compatible",
                    "label": "OpenAI 兼容接口",
                    "available": True,
                    "note": "填写 Base URL、模型 ID 与 API Key；用于接入兼容 OpenAI Chat Completions 的服务。",
                },
                {
                    "value": "anthropic_native",
                    "label": "Anthropic 原生接口",
                    "available": True,
                    "note": (
                        "直接调用 Anthropic Messages API。需要真实 API Key；Base URL 留空时使用官方地址，"
                        "也可填写自建代理地址。"
                    ),
                },
            ],
        }
    )


@router.post("/providers")
async def create_provider(
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.providers.create_llm_provider(as_payload(payload)))


@router.get("/providers/{provider_id}")
async def get_provider(provider_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.providers.get_llm_provider(provider_id))


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.providers.update_llm_provider(provider_id, as_payload(payload)))


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    await runtime.providers.delete_llm_provider(provider_id)
    return ok({"deleted": True, "id": provider_id})


@router.get("/providers/{provider_id}/models")
async def list_provider_models(provider_id: str, runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok(await runtime.providers.list_provider_models(provider_id))


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    return ok(
        await runtime.providers.test_llm_provider(
            provider_id,
            kind="connectivity",
            prompt=_prompt(data, required=False),
            max_output_tokens=_int_field(data, "max_output_tokens", 1, 32),
            operation_id=_operation_id(data),
        )
    )


@router.post("/providers/{provider_id}/test-generation")
async def test_provider_generation(
    provider_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    data = as_payload(payload)
    return ok(
        await runtime.providers.test_llm_provider(
            provider_id,
            kind="generation",
            prompt=_prompt(data, required=True),
            max_output_tokens=_int_field(data, "max_output_tokens", 1, 128),
            temperature=_temperature(data),
            operation_id=_operation_id(data),
        )
    )


@router.post("/providers/{provider_id}/operations/{operation_id}/cancel")
async def cancel_provider_operation(
    provider_id: str,
    operation_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.providers.cancel_provider_operation(provider_id, operation_id))


@router.get("/media/providers")
async def list_media_providers(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok({"items": await runtime.providers.list_media_providers()})


@router.get("/media/capabilities")
async def media_capabilities(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return ok({"items": await runtime.providers.capability_overview()})


@router.post("/media/providers/{provider_id}/enable")
async def enable_media_provider(
    provider_id: str,
    payload: dict[str, Any] | None = Body(default=None),
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    data = as_payload(payload)
    enabled = bool(data.get("enabled", True))
    return ok(await runtime.providers.set_media_provider_enabled(provider_id, enabled, actor=actor))


@router.post("/media/providers/{provider_id}/test")
async def test_media_provider(
    provider_id: str,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(await runtime.providers.test_media_provider(provider_id))


@router.get("/media/usage")
async def media_usage(
    hours: int = Query(24, ge=1, le=744),
    provider_id: str | None = None,
    capability: str | None = None,
    account_id: str | None = None,
    group_id: str | None = None,
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    return ok(
        await runtime.media_usage.aggregate(
            hours=hours,
            provider_id=provider_id,
            capability=capability,
            account_id=account_id,
            group_id=group_id,
        )
    )


@router.get("/media/jobs")
async def list_media_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    runtime: AppRuntime = Depends(get_runtime),
) -> dict[str, Any]:
    jobs = await runtime.media_jobs.list_jobs(limit=limit, status=status)
    return ok(
        {
            "items": [
                {
                    "id": job.id,
                    "job_type": job.job_type,
                    "capability": job.capability,
                    "media_ref": job.media_ref,
                    "provider_id": job.provider_id,
                    "status": job.status,
                    "attempts": job.attempts,
                    "max_attempts": job.max_attempts,
                    "error_code": job.error_code,
                    "error_message": job.error_message,
                    "output_ref": job.output_ref,
                    "deadline_at": job.deadline_at.isoformat() if job.deadline_at else None,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                }
                for job in jobs
            ],
            "note": "Mock 媒体任务的输出是模拟结果，不代表真实识别。",
        }
    )


@router.post("/media/jobs/{job_id}/cancel")
async def cancel_media_job(
    job_id: str,
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    job = await runtime.media_jobs.cancel_job(job_id)
    await write_audit(
        runtime.database,
        action="media.job.cancel",
        target_type="media_job",
        target_id=job.id,
        details={"capability": job.capability, "status": job.status},
        actor=actor,
    )
    return ok({"id": job.id, "status": job.status})


@router.post("/media/jobs/{job_id}/retry")
async def retry_media_job(
    job_id: str,
    runtime: AppRuntime = Depends(get_runtime),
    actor: str = Depends(get_actor),
) -> dict[str, Any]:
    job = await runtime.media_jobs.retry_job(job_id)
    await write_audit(
        runtime.database,
        action="media.job.retry",
        target_type="media_job",
        target_id=job.id,
        details={"capability": job.capability, "status": job.status},
        actor=actor,
    )
    return ok({"id": job.id, "status": job.status})


@router.post("/media/jobs/process-due")
async def process_due_media_jobs(runtime: AppRuntime = Depends(get_runtime)) -> dict[str, Any]:
    processed = await runtime.media_jobs.process_due_jobs(limit=10)
    return ok({"processed": processed})
