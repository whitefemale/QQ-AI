"""add optional auto memory extraction state

Revision ID: c8e2a4f1d609
Revises: b7c1e4a9d203
Create Date: 2026-10-25 18:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "c8e2a4f1d609"
down_revision: str | None = "b7c1e4a9d203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "auto_memory_extraction",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("memory_extraction_watermark_at", UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column("memory_extraction_last_run_at", UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column("memory_extraction_last_error", sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.drop_column("memory_extraction_last_error")
        batch_op.drop_column("memory_extraction_last_run_at")
        batch_op.drop_column("memory_extraction_watermark_at")
        batch_op.drop_column("auto_memory_extraction")
