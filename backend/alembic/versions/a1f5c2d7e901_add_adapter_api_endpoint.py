"""add adapter api_endpoint

Revision ID: a1f5c2d7e901
Revises: 3c8047b91bda
Create Date: 2026-10-25 09:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1f5c2d7e901"
down_revision: str | None = "3c8047b91bda"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("adapter_instances") as batch_op:
        batch_op.add_column(sa.Column("api_endpoint", sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("adapter_instances") as batch_op:
        batch_op.drop_column("api_endpoint")
