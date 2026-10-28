import asyncio

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from mallt.core.config import get_settings
from mallt.core.db import normalize_database_url
from mallt.models_registry import Base

config = context.config
target_metadata = Base.metadata


def _url() -> tuple[str, dict[str, object]]:
    # An explicit sqlalchemy.url (set by tests/tools) wins over the app settings.
    raw = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    return normalize_database_url(raw)


def run_migrations_offline() -> None:
    url, _ = _url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url, connect_args = _url()
    engine = create_async_engine(url, connect_args=connect_args)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
