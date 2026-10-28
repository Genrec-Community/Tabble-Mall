import httpx

from mallt.core.db import normalize_database_url


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
