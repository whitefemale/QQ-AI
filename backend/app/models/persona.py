"""人格档案、特征、版本与成长事件。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, new_id

DEFAULT_PERSONA_THRESHOLDS = {
    "min_evidence_count": 3,
    "min_conversations": 2,
    "min_confidence": 0.6,
    "min_messages_between_growth": 5,
    "max_traits_per_proposal": 5,
    "max_evidence_messages": 20,
}


class Persona(Base, TimestampMixin):
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), default="emergent", nullable=False)
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    self_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    authored_fields_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    system_prompt_overlay: Mapped[str | None] = mapped_column(Text, nullable=True)
    growth_policy: Mapped[str] = mapped_column(String(16), default="review", nullable=False)
    growth_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    learning_scope: Mapped[str] = mapped_column(String(32), default="admin_only", nullable=False)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    locked_fields_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    last_growth_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class PersonaVersion(Base, TimestampMixin):
    __tablename__ = "persona_versions"
    __table_args__ = (UniqueConstraint("persona_id", "version_no", name="uq_persona_versions_no"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("personas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    restorable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), default="system", nullable=False)


class PersonaTrait(Base, TimestampMixin):
    __tablename__ = "persona_traits"
    __table_args__ = (UniqueConstraint("persona_id", "trait_key", "source_scope", name="uq_persona_traits_key_scope"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("personas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trait_key: Mapped[str] = mapped_column(String(128), nullable=False)
    trait_value: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="style", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_message_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    source_scope: Mapped[str] = mapped_column(String(128), default="global", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="candidate", nullable=False)
    locked_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    first_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class PersonaEvolutionEvent(Base, TimestampMixin):
    __tablename__ = "persona_evolution_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    persona_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("personas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), default="auto", nullable=False)
    trigger_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    old_state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    new_state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    result: Mapped[str] = mapped_column(String(32), default="ignored", nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
