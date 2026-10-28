import httpx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mallt.core.db import SessionDep, defer_after_commit, normalize_database_url
from mallt.core.errors import Conflict, Unauthorized
from mallt.modules.tenancy.models import Organization


def test_normalize_neon_pooled_url() -> None:
    url, args = normalize_database_url(
        "postgresql://u:p@ep-x-pooler.eu.aws.neon.tech/db?sslmode=require&channel_binding=require"
    )
    assert url == "postgresql+asyncpg://u:p@ep-x-pooler.eu.aws.neon.tech/db"
    assert args == {"ssl": True, "statement_cache_size": 0}


def test_normalize_local_url_untouched() -> None:
    url, args = normalize_database_url("postgresql+asyncpg://postgres:test@localhost:5432/x")
    assert url == "postgresql+asyncpg://postgres:test@localhost:5432/x"
    assert args == {}


async def test_ready(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready"}


async def test_session_rolls_back_on_error_but_commits_when_the_error_asks_for_it(
    app: FastAPI, client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    @app.post("/api/v1/_test/org/{slug}")
    async def make(slug: str, session: SessionDep, fail: str = "") -> dict[str, str]:
        session.add(Organization(name=slug, slug=slug))
        await session.flush()
        if fail == "plain":
            raise Conflict("boom")
        if fail == "commit":
            raise CommitOnErrorForTest("boom")
        return {"ok": slug}

    async def count(slug: str) -> int:
        q = select(func.count()).select_from(Organization).where(Organization.slug == slug)
        return int((await db_session.execute(q)).scalar_one())

    assert (await client.post("/api/v1/_test/org/ok")).status_code == 200
    assert await count("ok") == 1
    assert (await client.post("/api/v1/_test/org/plain?fail=plain")).status_code == 409
    assert await count("plain") == 0  # rolled back with the error
    assert (await client.post("/api/v1/_test/org/kept?fail=commit")).status_code == 401
    assert await count("kept") == 1  # error response, but the work was committed


class CommitOnErrorForTest(Unauthorized):
    commit_on_error = True


async def test_after_commit_callbacks_run_only_when_the_work_commits(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    calls: list[str] = []

    @app.post("/api/v1/_test/defer/{mode}")
    async def defer(mode: str, session: SessionDep) -> dict[str, str]:
        async def later() -> None:
            calls.append(mode)

        defer_after_commit(session, later)
        if mode == "plain":
            raise Conflict("boom")
        if mode == "commit":
            raise CommitOnErrorForTest("boom")
        return {"ok": mode}

    assert (await client.post("/api/v1/_test/defer/ok")).status_code == 200
    assert (await client.post("/api/v1/_test/defer/plain")).status_code == 409
    assert (await client.post("/api/v1/_test/defer/commit")).status_code == 401
    assert calls == ["ok", "commit"]  # never for work that was rolled back
