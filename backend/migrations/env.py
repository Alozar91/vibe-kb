"""Alembic environment: metadata из app.models, URL из KB_DB_URL (code-standards §2.1)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.common.config import get_settings
from app.models import Base  # noqa: F401 — импорт тянет все модели для autogenerate

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline-режим: URL без подключения."""

    url = get_settings().db_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online-режим: engine из KB_DB_URL (не из alembic.ini — единый источник конфига)."""

    connectable = engine_from_config(
        {"sqlalchemy.url": get_settings().db_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
