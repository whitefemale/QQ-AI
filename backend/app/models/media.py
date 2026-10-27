"""媒体资产、异步处理任务与转写结果。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, new_id


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 内部 media_ref
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="stored", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class MediaJob(Base, TimestampMixin):
    __tablename__ = "media_processing_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    capability: Mapped[str] = mapped_column(String(32), nullable=False)
    media_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=30.0, nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class MediaTranscript(Base, TimestampMixin):
    __tablename__ = "media_transcripts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    media_ref: Mapped[str] = mapped_column(
        String(64), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="description", nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    timestamps_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MediaProviderUsage(Base, TimestampMixin):
    """媒体 Provider 调用审计（只含计数/时延/费用状态，不含媒体内容或转写文本）。"""

    __tablename__ = "media_provider_usage"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    capability: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="job", nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    requests: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    external_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
