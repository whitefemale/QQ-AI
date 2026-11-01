"""QQ 账号与连接器实例。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UTCDateTime, new_id


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), default="qq", nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    self_platform_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_private: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="disconnected", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    instances: Mapped[list[AdapterInstance]] = relationship(
        back_populates="account", cascade="all, delete-orphan", lazy="selectin"
    )


class AdapterInstance(Base, TimestampMixin):
    __tablename__ = "adapter_instances"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_adapter_instances_account_name"),
        UniqueConstraint("connector_installation_id", name="uq_adapter_instances_connector_installation_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), default="默认连接", nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    connection_mode: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    allow_remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_connect: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="disconnected", nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_received_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 受管连接器安装关联；每个安装最多一个自动配置的实例。
    connector_installation_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("connector_installations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    identity_confirmed_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    identity_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    account: Mapped[Account] = relationship(back_populates="instances")
