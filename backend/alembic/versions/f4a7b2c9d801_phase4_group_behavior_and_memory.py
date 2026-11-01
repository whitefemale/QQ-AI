"""phase 4 group behavior and memory fields

Revision ID: f4a7b2c9d801
Revises: d2e6b8a4c910
Create Date: 2026-10-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a7b2c9d801"
down_revision: str | None = "d2e6b8a4c910"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.add_column(sa.Column("max_reply_chars", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("context_message_limit", sa.Integer(), nullable=True))

    with op.batch_alter_table("outbox_messages", schema=None) as batch_op:
        batch_op.add_column(sa.Column("origin_member_platform_user_id", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("reply_kind", sa.String(length=32), nullable=False, server_default="reply")
        )
        batch_op.create_index(
            "ix_outbox_group_origin_sent",
            ["group_id", "origin_member_platform_user_id", "sent_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("outbox_messages", schema=None) as batch_op:
        batch_op.drop_index("ix_outbox_group_origin_sent")
        batch_op.drop_column("reply_kind")
        batch_op.drop_column("origin_member_platform_user_id")

    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.drop_column("context_message_limit")
        batch_op.drop_column("max_reply_chars")
