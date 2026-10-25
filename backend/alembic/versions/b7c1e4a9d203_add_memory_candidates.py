"""add memory candidates

Revision ID: b7c1e4a9d203
Revises: a1f5c2d7e901
Create Date: 2026-10-25 10:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "b7c1e4a9d203"
down_revision: str | None = "a1f5c2d7e901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_candidates",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("member_id", sa.String(length=64), nullable=True),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_message_ids_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=True),
        sa.Column("provider_type", sa.String(length=32), nullable=True),
        sa.Column("extraction_model", sa.String(length=128), nullable=True),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("reviewed_at", UTCDateTime(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=True),
        sa.Column("memory_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_memory_candidates_account_id_accounts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["groups.id"], name=op.f("fk_memory_candidates_group_id_groups"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"], ["memories.id"], name=op.f("fk_memory_candidates_memory_id_memories"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_candidates")),
    )
    with op.batch_alter_table("memory_candidates", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_memory_candidates_account_id"), ["account_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_candidates_group_id"), ["group_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_candidates_member_id"), ["member_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_candidates_status"), ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("memory_candidates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_memory_candidates_status"))
        batch_op.drop_index(batch_op.f("ix_memory_candidates_member_id"))
        batch_op.drop_index(batch_op.f("ix_memory_candidates_group_id"))
        batch_op.drop_index(batch_op.f("ix_memory_candidates_account_id"))

    op.drop_table("memory_candidates")
