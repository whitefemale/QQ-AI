"""add budget alert events

Revision ID: f5c8a1d4e230
Revises: e4a7c1b9f320
Create Date: 2026-10-25 22:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "f5c8a1d4e230"
down_revision: str | None = "e4a7c1b9f320"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "budget_alerts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=64), nullable=False),
        sa.Column("window", sa.String(length=16), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("period_key", sa.String(length=32), nullable=False),
        sa.Column("period_start", UTCDateTime(), nullable=True),
        sa.Column("used_value", sa.Float(), nullable=False),
        sa.Column("limit_value", sa.Float(), nullable=False),
        sa.Column("warn_threshold", sa.Float(), nullable=False),
        sa.Column("usage_ratio", sa.Float(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_alerts")),
        sa.UniqueConstraint(
            "policy_id",
            "period_key",
            "level",
            name="uq_budget_alert_policy_period_level",
        ),
    )
    with op.batch_alter_table("budget_alerts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_budget_alerts_policy_id"), ["policy_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_budget_alerts_level"), ["level"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("budget_alerts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_budget_alerts_level"))
        batch_op.drop_index(batch_op.f("ix_budget_alerts_policy_id"))
    op.drop_table("budget_alerts")
