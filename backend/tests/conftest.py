import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import httpx
import pytest
from alembic.config import Config
from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from alembic import command
from mallt.core.config import Settings
from mallt.core.db import get_session, make_engine
from mallt.core.kv import KV, PostgresKV, RedisKV
from mallt.main import create_app

BACKEND = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:test@localhost:5432/mallt_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL") or None


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def _ensure_database(url: str) -> None:
    """Create the test database if it does not exist yet."""
    plain = url.replace("+asyncpg", "")
    base, _, name = plain.rpartition("/")
    conn = await asyncpg.connect(f"{base}/postgres")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        env="test",
        database_url=TEST_DATABASE_URL,
        redis_url=TEST_REDIS_URL,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture(scope="session")
async def db_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    await _ensure_database(settings.database_url)
    engine = make_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    # Alembic's async env calls asyncio.run(), so run it off the test loop.
    await asyncio.to_thread(command.upgrade, _alembic_config(settings.database_url), "head")
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session whose work (including commits) is rolled back after each test."""
    conn: AsyncConnection = await db_engine.connect()
    outer = await conn.begin()
    session = AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield session
    finally:
        await session.close()
        await outer.rollback()
        await conn.close()


@pytest.fixture(params=["postgres", "redis"])
async def kv(request: pytest.FixtureRequest, db_engine: AsyncEngine) -> AsyncIterator[KV]:
    """Every KV test runs against both backends (redis only when TEST_REDIS_URL is set)."""
    if request.param == "redis":
        if not TEST_REDIS_URL:
            pytest.skip("TEST_REDIS_URL not set")
        backend: KV = RedisKV.from_url(TEST_REDIS_URL)
        await backend.flush()
    else:
        backend = PostgresKV(db_engine)
        await backend.flush()
    yield backend
    await backend.flush()
    await backend.aclose()


class _Echo(BaseModel):
    n: int


@pytest.fixture
async def app(settings: Settings, db_session: AsyncSession) -> AsyncIterator[FastAPI]:
    app = create_app(settings)

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session
        await db_session.commit()

    app.dependency_overrides[get_session] = _session

    @app.post("/api/v1/_test/echo")
    async def echo(body: _Echo) -> _Echo:
        return body

    yield app
    # kv state lives outside the per-test transaction, so wipe it after each test.
    await app.state.kv.flush()
    await app.state.kv.aclose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
