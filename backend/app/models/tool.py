"""工具注册与执行记录。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_id


class ToolRecord(Base, TimestampMixin):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_type: Mapped[str] = mapped_column(String(32), default="builtin", nullable=False)
    input_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    required_permissions_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ToolRun(Base, TimestampMixin):
    __tablename__ = "tool_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    tool_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
