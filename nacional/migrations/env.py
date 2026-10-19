from alembic import context
from sqlalchemy import create_engine

import app.models  # noqa: F401  (registra las tablas)
from app.db import Base, engine

target_metadata = Base.metadata


def _engine():
    # Los tests pasan su propia URL (sqlalchemy.url); por defecto se usa DATABASE_URL.
    url = context.config.get_main_option("sqlalchemy.url")
    return create_engine(url) if url else engine


def run_migrations_offline() -> None:
    context.configure(url=str(_engine().url), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with _engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
