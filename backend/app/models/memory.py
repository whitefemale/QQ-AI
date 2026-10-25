"""长期记忆：手动管理、AI 候选提取（人工审核）与当前群范围内的受控检索。

后台提取为群级可选、只生成待审核候选；摘要压缩、语义向量检索与冲突检测仍为后续能力。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, new_id

MEMORY_CANDIDATE_STATUSES = {"pending", "approved", "rejected"}


class Memory(Base, TimestampMixin):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    member_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), default="fact", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    embedding_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)


class MemoryCandidate(Base, TimestampMixin):
    """模型提取出的待审核记忆；只有批准后才会写入 memories。"""

    __tablename__ = "memory_candidates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), default="fact", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    extraction_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    memory_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
