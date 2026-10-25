"""add memory extraction watermark message id

Revision ID: d9f3b6a2c715
Revises: c8e2a4f1d609
Create Date: 2026-10-25 19:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9f3b6a2c715"
down_revision: str | None = "c8e2a4f1d609"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 与时间水位线联合使用，避免同一秒内的消息在增量扫描时被跳过。
    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.add_column(sa.Column("memory_extraction_watermark_message_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.drop_column("memory_extraction_watermark_message_id")
