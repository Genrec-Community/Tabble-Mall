from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from mallt.core.config import Settings
from mallt.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(env="test")


class _Echo(BaseModel):
    n: int


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    @app.post("/api/v1/_test/echo")
    async def echo(body: _Echo) -> _Echo:
        return body

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
