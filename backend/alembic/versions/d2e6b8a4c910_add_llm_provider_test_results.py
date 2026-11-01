"""add persisted llm provider test results

Revision ID: d2e6b8a4c910
Revises: b8d4e2f6a130
Create Date: 2026-10-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2e6b8a4c910"
down_revision: str | None = "b8d4e2f6a130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("llm_providers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_test_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("last_generation_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("llm_providers", schema=None) as batch_op:
        batch_op.drop_column("last_generation_json")
        batch_op.drop_column("last_test_json")
