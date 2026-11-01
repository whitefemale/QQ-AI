"""add connector manager tables and instance identity fields

Revision ID: b8d4e2f6a130
Revises: a7b3c9d1e240
Create Date: 2026-10-31 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "b8d4e2f6a130"
down_revision: str | None = "a7b3c9d1e240"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_installations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("root_path", sa.String(length=1024), nullable=False),
        sa.Column("shell_path", sa.String(length=1024), nullable=True),
        sa.Column("config_relative_path", sa.String(length=512), nullable=True),
        sa.Column("layout_confidence", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("managed", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("license_json", sa.JSON(), nullable=False),
        sa.Column("installer_launched_at", UTCDateTime(), nullable=True),
        sa.Column("last_seen_at", UTCDateTime(), nullable=True),
        sa.Column("last_state", sa.String(length=48), nullable=False),
        sa.Column("last_evidence_json", sa.JSON(), nullable=False),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_installations")),
    )
    with op.batch_alter_table("connector_installations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_connector_installations_kind"), ["kind"], unique=False)
        batch_op.create_index(batch_op.f("ix_connector_installations_active"), ["active"], unique=False)

    op.create_table(
        "connector_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("target_path", sa.String(length=1024), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("log_tail", sa.Text(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_jobs")),
    )
    with op.batch_alter_table("connector_jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_connector_jobs_kind"), ["kind"], unique=False)
        batch_op.create_index(batch_op.f("ix_connector_jobs_state"), ["state"], unique=False)

    op.create_table(
        "connector_config_snapshots",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("snapshot_group", sa.String(length=64), nullable=False),
        sa.Column("installation_id", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("restored_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_config_snapshots")),
    )
    with op.batch_alter_table("connector_config_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_connector_config_snapshots_snapshot_group"), ["snapshot_group"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_connector_config_snapshots_installation_id"), ["installation_id"], unique=False
        )

    with op.batch_alter_table("adapter_instances", schema=None) as batch_op:
        batch_op.add_column(sa.Column("connector_installation_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("identity_confirmed_user_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("identity_confirmed_at", UTCDateTime(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_adapter_instances_connector_installation_id"),
            ["connector_installation_id"],
            unique=False,
        )
        batch_op.create_unique_constraint(
            "uq_adapter_instances_connector_installation_id",
            ["connector_installation_id"],
        )
        batch_op.create_foreign_key(
            "fk_adapter_instances_connector_installation_id_connector_installations",
            "connector_installations",
            ["connector_installation_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("adapter_instances", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_adapter_instances_connector_installation_id_connector_installations",
            type_="foreignkey",
        )
        batch_op.drop_constraint("uq_adapter_instances_connector_installation_id", type_="unique")
        batch_op.drop_index(batch_op.f("ix_adapter_instances_connector_installation_id"))
        batch_op.drop_column("identity_confirmed_at")
        batch_op.drop_column("identity_confirmed_user_id")
        batch_op.drop_column("connector_installation_id")

    with op.batch_alter_table("connector_config_snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_connector_config_snapshots_installation_id"))
        batch_op.drop_index(batch_op.f("ix_connector_config_snapshots_snapshot_group"))
    op.drop_table("connector_config_snapshots")

    with op.batch_alter_table("connector_jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_connector_jobs_state"))
        batch_op.drop_index(batch_op.f("ix_connector_jobs_kind"))
    op.drop_table("connector_jobs")

    with op.batch_alter_table("connector_installations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_connector_installations_active"))
        batch_op.drop_index(batch_op.f("ix_connector_installations_kind"))
    op.drop_table("connector_installations")
