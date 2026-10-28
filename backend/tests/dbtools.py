"""Helpers shared by conftest and migration tests."""

import os
from pathlib import Path

import asyncpg
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:test@localhost:5432/mallt_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL") or None


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def with_database(url: str, name: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{name}"


async def ensure_database(url: str) -> None:
    """Create the database named in ``url`` if it does not exist yet."""
    plain = url.replace("+asyncpg", "")
    base, _, name = plain.rpartition("/")
    conn = await asyncpg.connect(f"{base}/postgres")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
