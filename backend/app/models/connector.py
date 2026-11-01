"""受管连接器安装、安装任务与配置快照。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, new_id


class ConnectorInstallation(Base, TimestampMixin):
    """一个受管或只读可检测的连接器安装。

    ``root_path`` / ``shell_path`` 只保存在服务端，对外响应最小化显示；
    是否受管由 manifest 验证决定，不能仅凭目录存在推断。
    """

    __tablename__ = "connector_installations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), default="napcat", nullable=False, index=True)
    root_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    shell_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    config_relative_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    layout_confidence: Mapped[str] = mapped_column(String(32), default="unverified", nullable=False)
    version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="managed_release", nullable=False)
    managed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    license_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    installer_launched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_state: Mapped[str] = mapped_column(String(48), default="not_installed", nullable=False)
    last_evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConnectorJob(Base, TimestampMixin):
    """安装/升级/版本查询后台任务；不持久化子进程 PID。"""

    __tablename__ = "connector_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(32), default="install", nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    target_path: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(64), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    log_tail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    actor: Mapped[str] = mapped_column(String(64), default="local-admin", nullable=False)


class ConnectorConfigSnapshot(Base, TimestampMixin):
    """连接器配置文件的加密快照；内容绝不进入普通日志或 API 响应。"""

    __tablename__ = "connector_config_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    snapshot_group: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    installation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    encrypted_content: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(64), default="apply", nullable=False)
    restored_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


__all__ = ["ConnectorConfigSnapshot", "ConnectorInstallation", "ConnectorJob"]
