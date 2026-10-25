"""Alembic 迁移环境。使用同步 SQLite URL，与应用共享同一份配置。"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.db.base import Base, UTCDateTime  # noqa: E402
import app.models  # noqa: F401,E402


def render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "UTCDateTime()"
    return False


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = config.attributes.get("settings") or Settings()
config.set_main_option("sqlalchemy.url", settings.database_sync_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings.ensure_directories()
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
