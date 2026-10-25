"""add group llm provider routing

Revision ID: e4a7c1b9f320
Revises: d9f3b6a2c715
Create Date: 2026-10-25 21:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7c1b9f320"
down_revision: str | None = "d9f3b6a2c715"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 群级主/备用模型均为可空绑定；未绑定时继续使用全局默认 Provider。
    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.add_column(sa.Column("llm_provider_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("llm_fallback_provider_id", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_groups_llm_provider_id",
            "llm_providers",
            ["llm_provider_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_groups_llm_fallback_provider_id",
            "llm_providers",
            ["llm_fallback_provider_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_groups_llm_provider_id", ["llm_provider_id"], unique=False)
        batch_op.create_index(
            "ix_groups_llm_fallback_provider_id",
            ["llm_fallback_provider_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("groups", schema=None) as batch_op:
        batch_op.drop_index("ix_groups_llm_fallback_provider_id")
        batch_op.drop_index("ix_groups_llm_provider_id")
        batch_op.drop_constraint("fk_groups_llm_fallback_provider_id", type_="foreignkey")
        batch_op.drop_constraint("fk_groups_llm_provider_id", type_="foreignkey")
        batch_op.drop_column("llm_fallback_provider_id")
        batch_op.drop_column("llm_provider_id")
