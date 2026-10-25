"""系统设置、审计、插件、任务、预算、备份与 P1 骨架表。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, new_id


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(64), default="local-admin", nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PluginRegistry(Base, TimestampMixin):
    __tablename__ = "plugin_registry"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), default="0.0.1", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    plugin_type: Mapped[str] = mapped_column(String(32), default="local", nullable=False)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    permissions_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    config_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    dependencies_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    min_app_version: Mapped[str] = mapped_column(String(32), default="0.1.0", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    permission_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TaskRun(Base, TimestampMixin):
    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BudgetPolicy(Base, TimestampMixin):
    __tablename__ = "budget_policies"
    __table_args__ = (
        UniqueConstraint("scope_type", "scope_id", "window", "metric", name="uq_budget_scope_window_metric"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    scope_type: Mapped[str] = mapped_column(String(32), default="global", nullable=False)
    scope_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    window: Mapped[str] = mapped_column(String(16), default="day", nullable=False)
    metric: Mapped[str] = mapped_column(String(32), default="requests", nullable=False)
    limit_value: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    warn_threshold: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)
    action: Mapped[str] = mapped_column(String(16), default="pause", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BudgetAlert(Base, TimestampMixin):
    """预算阈值告警事件。

    同一策略在同一统计周期内只记录一次 warning / exceeded，
    避免每次模型调用都重复写入；事件本身不修改预算状态。
    """

    __tablename__ = "budget_alerts"
    __table_args__ = (
        UniqueConstraint(
            "policy_id",
            "period_key",
            "level",
            name="uq_budget_alert_policy_period_level",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    window: Mapped[str] = mapped_column(String(16), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    used_value: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    limit_value: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    warn_threshold: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    usage_ratio: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class UsageEvent(Base, TimestampMixin):
    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    scope_type: Mapped[str] = mapped_column(String(32), default="global", nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    feature: Mapped[str] = mapped_column(String(32), default="reply", nullable=False)
    metric: Mapped[str] = mapped_column(String(32), default="requests", nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)


class BackupRecord(Base, TimestampMixin):
    __tablename__ = "backup_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    app_version: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    includes_secrets: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RetentionPolicy(Base, TimestampMixin):
    __tablename__ = "retention_policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    data_type: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AutomationRule(Base, TimestampMixin):
    __tablename__ = "automation_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_type: Mapped[str] = mapped_column(String(32), default="keyword", nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ConversationEvalCase(Base, TimestampMixin):
    __tablename__ = "conversation_eval_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    expected_labels_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)


class ConversationEvalRun(Base, TimestampMixin):
    __tablename__ = "conversation_eval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
