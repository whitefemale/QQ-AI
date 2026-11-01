from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.core.config import Settings
from app.core.schema_version import head_revision
from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_REVISION = "f5c8a1d4e230"
CONNECTOR_BASE_REVISION = "a7b3c9d1e240"
PROVIDER_TEST_BASE_REVISION = "b8d4e2f6a130"
PHASE4_BASE_REVISION = "d2e6b8a4c910"


def _config(settings: Settings) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.attributes["settings"] = settings
    return config


def test_upgraded_database_matches_code_head(settings: Settings) -> None:
    config = _config(settings)
    command.upgrade(config, "head")

    engine = create_engine(settings.database_sync_url)
    try:
        with engine.connect() as connection:
            current = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()

    code_head = head_revision()
    assert code_head is not None
    assert current == code_head


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
        assert {"connector_installations", "connector_jobs", "connector_config_snapshots"} <= set(
            inspector.get_table_names()
        )
        instance_columns = {column["name"] for column in inspector.get_columns("adapter_instances")}
        assert {
            "connector_installation_id",
            "identity_confirmed_user_id",
            "identity_confirmed_at",
        } <= instance_columns
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
        assert "connector_installations" not in inspector.get_table_names()
        assert "identity_confirmed_at" not in {column["name"] for column in inspector.get_columns("adapter_instances")}
    finally:
        engine.dispose()

    command.upgrade(config, "head")


def test_connector_migration_single_step_round_trip(settings: Settings) -> None:
    config = _config(settings)
    command.upgrade(config, "head")

    # 显式指定连接器迁移之前的版本；不能用 -1，否则只会回滚最新的 Provider 测试列。
    command.downgrade(config, CONNECTOR_BASE_REVISION)
    engine = create_engine(settings.database_sync_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "connector_installations" not in tables
        assert "connector_jobs" not in tables
        assert "connector_config_snapshots" not in tables
        adapter_columns = {column["name"] for column in inspector.get_columns("adapter_instances")}
        assert "connector_installation_id" not in adapter_columns
        assert "identity_confirmed_user_id" not in adapter_columns
        assert "identity_confirmed_at" not in adapter_columns
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(settings.database_sync_url)
    try:
        inspector = inspect(engine)
        assert {"connector_installations", "connector_jobs", "connector_config_snapshots"} <= set(
            inspector.get_table_names()
        )
        adapter_columns = {column["name"] for column in inspector.get_columns("adapter_instances")}
        assert "identity_confirmed_at" in adapter_columns
    finally:
        engine.dispose()


def test_provider_test_result_migration_round_trip(settings: Settings) -> None:
    config = _config(settings)
    command.upgrade(config, "head")
    engine = create_engine(settings.database_sync_url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("llm_providers")}
        assert {"last_test_json", "last_generation_json"} <= columns
    finally:
        engine.dispose()

    command.downgrade(config, PROVIDER_TEST_BASE_REVISION)
    engine = create_engine(settings.database_sync_url)
    try:
        inspector = inspect(engine)
        columns = {column["name"] for column in inspector.get_columns("llm_providers")}
        assert "last_test_json" not in columns
        assert "last_generation_json" not in columns
        # 只回滚本级迁移，连接器表仍应保留。
        assert "connector_installations" in inspector.get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(settings.database_sync_url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("llm_providers")}
        assert {"last_test_json", "last_generation_json"} <= columns
    finally:
        engine.dispose()


def test_phase4_migration_round_trip(settings: Settings) -> None:
    config = _config(settings)
    command.upgrade(config, "head")
    engine = create_engine(settings.database_sync_url)
    try:
        inspector = inspect(engine)
        group_columns = {column["name"] for column in inspector.get_columns("groups")}
        assert {"max_reply_chars", "context_message_limit"} <= group_columns
        outbox_columns = {column["name"] for column in inspector.get_columns("outbox_messages")}
        assert {"origin_member_platform_user_id", "reply_kind"} <= outbox_columns
        assert "ix_outbox_group_origin_sent" in {index["name"] for index in inspector.get_indexes("outbox_messages")}
    finally:
        engine.dispose()

    command.downgrade(config, PHASE4_BASE_REVISION)
    engine = create_engine(settings.database_sync_url)
    try:
        inspector = inspect(engine)
        group_columns = {column["name"] for column in inspector.get_columns("groups")}
        assert "max_reply_chars" not in group_columns
        assert "context_message_limit" not in group_columns
        outbox_columns = {column["name"] for column in inspector.get_columns("outbox_messages")}
        assert "origin_member_platform_user_id" not in outbox_columns
        assert "reply_kind" not in outbox_columns
        assert "ix_outbox_group_origin_sent" not in {
            index["name"] for index in inspector.get_indexes("outbox_messages")
        }
        # 只回滚本级迁移，Provider 测试列仍应保留。
        assert "last_test_json" in {column["name"] for column in inspector.get_columns("llm_providers")}
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
