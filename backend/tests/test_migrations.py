from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.core.config import Settings
from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "f5c8a1d4e230"


def _config(settings: Settings) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.attributes["settings"] = settings
    return config


def test_migration_round_trip_creates_phase1_fields(settings: Settings) -> None:
    config = _config(settings)
    command.upgrade(config, "head")

    engine = create_engine(settings.database_sync_url)
    try:
        inspector = inspect(engine)
        assert "media_provider_usage" in inspector.get_table_names()

        assert "account_id" in {column["name"] for column in inspector.get_columns("llm_usage")}
        assert "diff_summary" in {column["name"] for column in inspector.get_columns("persona_evolution_events")}
        assert "healthcheck_json" in {column["name"] for column in inspector.get_columns("plugin_registry")}

        assert "ix_messages_event_timestamp" in {index["name"] for index in inspector.get_indexes("messages")}
        assert "ix_media_assets_expires_at" in {index["name"] for index in inspector.get_indexes("media_assets")}
        assert "ix_usage_events_scope_feature_window" in {
            index["name"] for index in inspector.get_indexes("usage_events")
        }
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_REVISION)
    engine = create_engine(settings.database_sync_url)
    try:
        inspector = inspect(engine)
        assert "media_provider_usage" not in inspector.get_table_names()
        assert "account_id" not in {column["name"] for column in inspector.get_columns("llm_usage")}
        assert "diff_summary" not in {column["name"] for column in inspector.get_columns("persona_evolution_events")}
        assert "healthcheck_json" not in {column["name"] for column in inspector.get_columns("plugin_registry")}
        assert "ix_messages_event_timestamp" not in {index["name"] for index in inspector.get_indexes("messages")}
        assert "ix_usage_events_scope_feature_window" not in {
            index["name"] for index in inspector.get_indexes("usage_events")
        }
    finally:
        engine.dispose()

    command.upgrade(config, "head")


def test_feature_key_data_migration_reply_to_chat_and_back(settings: Settings) -> None:
    config = _config(settings)
    command.upgrade(config, "head")
    command.downgrade(config, PREVIOUS_REVISION)

    engine = create_engine(settings.database_sync_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO usage_events "
                    "(id, scope_type, scope_id, feature, metric, amount, currency, created_at, updated_at) "
                    "VALUES (:id, :scope_type, :scope_id, :feature, :metric, :amount, :currency, :created_at, :updated_at)"
                ),
                {
                    "id": "legacy-reply",
                    "scope_type": "global",
                    "scope_id": "",
                    "feature": "reply",
                    "metric": "requests",
                    "amount": 1.0,
                    "currency": "USD",
                    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                    "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
                },
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(settings.database_sync_url)
    try:
        with engine.connect() as connection:
            feature = connection.scalar(text("SELECT feature FROM usage_events WHERE id = 'legacy-reply'"))
        assert feature == "chat"
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_REVISION)
    engine = create_engine(settings.database_sync_url)
    try:
        with engine.connect() as connection:
            feature = connection.scalar(text("SELECT feature FROM usage_events WHERE id = 'legacy-reply'"))
        assert feature == "reply"
    finally:
        engine.dispose()

    command.upgrade(config, "head")
