"""媒体处理任务：幂等、超时、有限重试、取消与结果保存。"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.media.base import ASRProvider, EmbeddingProvider, OCRProvider, VisionProvider
from app.core.errors import AppError, ErrorCode
from app.core.time import utcnow
from app.db.session import Database
from app.media.capability_router import CapabilityRouter
from app.media.service import MediaService
from app.models.media import MediaJob, MediaTranscript
from app.schemas.media import (
    AudioTranscriptionRequest,
    ImageUnderstandRequest,
    OCRRequest,
)


class MediaJobService:
    def __init__(self, database: Database, router: CapabilityRouter, media_service: MediaService) -> None:
        self.database = database
        self.router = router
        self.media_service = media_service
        self._locks: dict[str, asyncio.Lock] = {}

    async def create_job(
        self,
        *,
        capability: str,
        media_ref: str,
        job_type: str,
        input_data: dict[str, Any] | None = None,
        idempotency_key: str,
        timeout_seconds: float = 30.0,
        max_attempts: int = 2,
    ) -> MediaJob:
        async with self.database.session() as session:
            existing = await session.scalar(select(MediaJob).where(MediaJob.idempotency_key == idempotency_key))
            if existing is not None:
                return existing
            job = MediaJob(
                job_type=job_type,
                capability=capability,
                media_ref=media_ref,
                status="queued",
                attempts=0,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                deadline_at=utcnow() + timedelta(seconds=timeout_seconds * max(1, max_attempts)),
                idempotency_key=idempotency_key,
                input_json=input_data or {},
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    async def get_job(self, job_id: str) -> MediaJob:
        async with self.database.session() as session:
            job = await session.get(MediaJob, job_id)
        if job is None:
            raise AppError(ErrorCode.MEDIA_JOB_NOT_FOUND, "媒体任务不存在。", status_code=404)
        return job

    async def list_jobs(self, limit: int = 50, status: str | None = None) -> list[MediaJob]:
        async with self.database.session() as session:
            query = select(MediaJob).order_by(MediaJob.created_at.desc()).limit(limit)
            if status:
                query = query.where(MediaJob.status == status)
            result = await session.execute(query)
            return list(result.scalars())

    def _lock(self, job_id: str) -> asyncio.Lock:
        return self._locks.setdefault(job_id, asyncio.Lock())

    async def process_job(self, job_id: str) -> MediaJob:
        async with self._lock(job_id):
            async with self.database.session() as session:
                job = await session.get(MediaJob, job_id)
                if job is None:
                    raise AppError(ErrorCode.MEDIA_JOB_NOT_FOUND, "媒体任务不存在。", status_code=404)
                if job.status not in {"queued"}:
                    return job
                job.status = "running"
                job.attempts += 1
                job.started_at = utcnow()
                await session.commit()
                await session.refresh(job)

            provider = None
            try:
                provider, _decision = self.router.select(job.capability)
                job.provider_id = provider.provider_id
                result, kind = await asyncio.wait_for(self._invoke(provider, job), timeout=job.timeout_seconds)
                async with self.database.session() as session:
                    current = await session.get(MediaJob, job.id)
                    assert current is not None
                    if current.status == "cancelled":
                        return current
                    transcript = MediaTranscript(
                        media_ref=current.media_ref,
                        job_id=current.id,
                        kind=kind,
                        text=result.get("text", ""),
                        language=result.get("language"),
                        timestamps_json=result.get("timestamps", []),
                        provider_id=provider.provider_id,
                        confidence=result.get("confidence"),
                        is_mock=bool(result.get("is_mock")),
                    )
                    session.add(transcript)
                    await session.flush()
                    current.status = "succeeded"
                    current.output_ref = transcript.id
                    current.error_code = None
                    current.error_message = None
                    current.finished_at = utcnow()
                    await session.commit()
                    await session.refresh(current)
                    return current
            except TimeoutError:
                return await self._mark_failure(job.id, ErrorCode.MEDIA_JOB_RETRY_EXHAUSTED, "媒体处理超时。")
            except AppError as exc:
                return await self._mark_failure(job.id, exc.code, exc.message)
            except Exception as exc:  # pragma: no cover - 防御性
                return await self._mark_failure(job.id, ErrorCode.INTERNAL_ERROR, f"媒体处理异常：{type(exc).__name__}")

    async def _invoke(self, provider: Any, job: MediaJob) -> tuple[dict[str, Any], str]:
        if job.capability == "image.describe":
            assert isinstance(provider, VisionProvider)
            vision_result = await provider.describe_image(
                ImageUnderstandRequest(media_ref=job.media_ref, mime=job.input_json.get("mime"))
            )
            return {
                "text": vision_result.summary,
                "confidence": vision_result.confidence,
                "is_mock": vision_result.is_mock,
            }, "description"
        if job.capability == "ocr.extract":
            assert isinstance(provider, OCRProvider)
            ocr_result = await provider.extract_text(
                OCRRequest(media_ref=job.media_ref, mime=job.input_json.get("mime"))
            )
            return {
                "text": ocr_result.text,
                "language": ocr_result.language,
                "confidence": ocr_result.confidence,
                "is_mock": ocr_result.is_mock,
            }, "ocr"
        if job.capability == "audio.transcribe":
            assert isinstance(provider, ASRProvider)
            asr_result = await provider.transcribe(
                AudioTranscriptionRequest(media_ref=job.media_ref, mime=job.input_json.get("mime"))
            )
            return {
                "text": asr_result.text,
                "language": asr_result.language,
                "timestamps": asr_result.timestamps,
                "confidence": asr_result.confidence,
                "is_mock": asr_result.is_mock,
            }, "transcript"
        if job.capability == "text.embed":
            assert isinstance(provider, EmbeddingProvider)
            vectors = await provider.embed([str(job.input_json.get("text", ""))])
            return {"text": json.dumps(vectors), "is_mock": True}, "embedding"
        raise AppError(
            ErrorCode.PROVIDER_CAPABILITY_MISSING,
            "该媒体任务类型尚未实现。",
            status_code=501,
        )

    async def _mark_failure(self, job_id: str, code: str, message: str) -> MediaJob:
        async with self.database.session() as session:
            job = await session.get(MediaJob, job_id)
            if job is None:
                raise AppError(ErrorCode.MEDIA_JOB_NOT_FOUND, "媒体任务不存在。", status_code=404)
            job.error_code = code
            job.error_message = message
            if job.attempts < job.max_attempts:
                job.status = "queued"
            else:
                job.status = "failed"
                job.finished_at = utcnow()
            await session.commit()
            await session.refresh(job)
            return job

    async def cancel_job(self, job_id: str) -> MediaJob:
        async with self.database.session() as session:
            job = await session.get(MediaJob, job_id)
            if job is None:
                raise AppError(ErrorCode.MEDIA_JOB_NOT_FOUND, "媒体任务不存在。", status_code=404)
            if job.status != "queued":
                raise AppError(
                    ErrorCode.MEDIA_JOB_CANNOT_CANCEL,
                    "只能取消尚未开始处理的任务。",
                    status_code=400,
                )
            job.status = "cancelled"
            job.finished_at = utcnow()
            await session.commit()
            await session.refresh(job)
            return job

    async def retry_job(self, job_id: str) -> MediaJob:
        async with self.database.session() as session:
            job = await session.get(MediaJob, job_id)
            if job is None:
                raise AppError(ErrorCode.MEDIA_JOB_NOT_FOUND, "媒体任务不存在。", status_code=404)
            if job.status not in {"failed", "cancelled"}:
                raise AppError(ErrorCode.MEDIA_JOB_CANNOT_CANCEL, "当前状态不能重试。", status_code=400)
            if job.attempts >= job.max_attempts:
                raise AppError(ErrorCode.MEDIA_JOB_RETRY_EXHAUSTED, "已达到最大重试次数。", status_code=400)
            job.status = "queued"
            job.error_code = None
            job.error_message = None
            job.finished_at = None
            await session.commit()
            await session.refresh(job)
            return job

    async def process_due_jobs(self, limit: int = 5) -> int:
        async with self.database.session() as session:
            result = await session.execute(
                select(MediaJob).where(MediaJob.status == "queued").order_by(MediaJob.created_at).limit(limit)
            )
            job_ids = [job.id for job in result.scalars()]
        for job_id in job_ids:
            await self.process_job(job_id)
        return len(job_ids)

    async def process_segment(
        self,
        *,
        media_ref: str,
        media_type: str,
        account_id: str | None,
        group_id: str | None,
        source_message_id: str,
    ) -> MediaTranscript | None:
        """根据消息媒体段自动补全描述/转写；无可用 Provider 时返回 None。"""
        capability_map = {
            "image": "image.describe",
            "sticker": "image.describe",
            "audio": "audio.transcribe",
        }
        capability = capability_map.get(media_type)
        if capability is None:
            return None
        try:
            provider, _ = self.router.select(capability)
        except AppError:
            return None
        idempotency = f"{media_ref}:{capability}:{source_message_id}"
        job = await self.create_job(
            capability=capability,
            media_ref=media_ref,
            job_type=media_type,
            input_data={"account_id": account_id, "group_id": group_id, "mime": None},
            idempotency_key=idempotency,
        )
        if job.status == "succeeded" and job.output_ref:
            async with self.database.session() as session:
                return await session.get(MediaTranscript, job.output_ref)
        processed = await self.process_job(job.id)
        if processed.status == "succeeded" and processed.output_ref:
            async with self.database.session() as session:
                return await session.get(MediaTranscript, processed.output_ref)
        return None


async def list_media_transcripts_for_message(session: AsyncSession, media_ref: str) -> list[MediaTranscript]:
    result = await session.execute(
        select(MediaTranscript).where(MediaTranscript.media_ref == media_ref).order_by(MediaTranscript.created_at)
    )
    return list(result.scalars())
