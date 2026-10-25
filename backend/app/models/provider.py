"""LLM Provider、能力注册表与用量。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, new_id


class LLMProvider(Base, TimestampMixin):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), default="openai_compatible", nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=45.0, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=800, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unconfigured", nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ProviderRegistry(Base, TimestampMixin):
    __tablename__ = "provider_registry"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    config_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unconfigured", nullable=False)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    planned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_health_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class LLMUsage(Base, TimestampMixin):
    __tablename__ = "llm_usage"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    purpose: Mapped[str] = mapped_column(String(32), default="reply", nullable=False, index=True)
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
