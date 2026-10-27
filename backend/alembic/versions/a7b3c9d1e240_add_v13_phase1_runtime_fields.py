"""add V1.3 phase 1 runtime fields

Revision ID: a7b3c9d1e240
Revises: f5c8a1d4e230
Create Date: 2026-10-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.base import UTCDateTime

revision: str = "a7b3c9d1e240"
down_revision: str | None = "f5c8a1d4e230"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("llm_usage", schema=None) as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_llm_usage_account_id"), ["account_id"], unique=False)

    with op.batch_alter_table("persona_evolution_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("diff_summary", sa.Text(), nullable=True))

    with op.batch_alter_table("plugin_registry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("healthcheck_json", sa.JSON(), nullable=True))

    op.create_table(
        "media_provider_usage",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=128), nullable=True),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=True),
        sa.Column("group_id", sa.String(length=64), nullable=True),
        sa.Column("requests", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("external_cost", sa.Float(), nullable=True),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_provider_usage")),
    )
    with op.batch_alter_table("media_provider_usage", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_media_provider_usage_provider_id"), ["provider_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_media_provider_usage_capability"), ["capability"], unique=False)
        batch_op.create_index(batch_op.f("ix_media_provider_usage_account_id"), ["account_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_media_provider_usage_group_id"), ["group_id"], unique=False)

    op.create_index("ix_messages_event_timestamp", "messages", ["event_timestamp"], unique=False)
    op.create_index("ix_media_assets_expires_at", "media_assets", ["expires_at"], unique=False)
    op.create_index("ix_media_assets_source_message_id", "media_assets", ["source_message_id"], unique=False)
    op.create_index(
        "ix_usage_events_scope_feature_window",
        "usage_events",
        ["scope_type", "scope_id", "feature", "metric", "window_start"],
        unique=False,
    )

    # 统一功能键：历史回复用量归入 chat；不改变 LLMRequest.purpose 的原始值。
    op.execute("UPDATE usage_events SET feature = 'chat' WHERE feature = 'reply'")


def downgrade() -> None:
    op.execute("UPDATE usage_events SET feature = 'reply' WHERE feature = 'chat'")

    op.drop_index("ix_usage_events_scope_feature_window", table_name="usage_events")
    op.drop_index("ix_media_assets_source_message_id", table_name="media_assets")
    op.drop_index("ix_media_assets_expires_at", table_name="media_assets")
    op.drop_index("ix_messages_event_timestamp", table_name="messages")

    with op.batch_alter_table("media_provider_usage", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_media_provider_usage_group_id"))
        batch_op.drop_index(batch_op.f("ix_media_provider_usage_account_id"))
        batch_op.drop_index(batch_op.f("ix_media_provider_usage_capability"))
        batch_op.drop_index(batch_op.f("ix_media_provider_usage_provider_id"))
    op.drop_table("media_provider_usage")

    with op.batch_alter_table("plugin_registry", schema=None) as batch_op:
        batch_op.drop_column("healthcheck_json")

    with op.batch_alter_table("persona_evolution_events", schema=None) as batch_op:
        batch_op.drop_column("diff_summary")

    with op.batch_alter_table("llm_usage", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_llm_usage_account_id"))
        batch_op.drop_column("account_id")
