import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from mallt.core.bus import Bus, MemoryBus, PostgresBus, RedisBus
from tests.dbtools import TEST_DATABASE_URL, TEST_REDIS_URL


@pytest.fixture(params=["memory", "postgres", "redis"])
async def bus(request: pytest.FixtureRequest, db_engine: AsyncEngine) -> AsyncIterator[Bus]:
    if request.param == "memory":
        b: Bus = MemoryBus()
    elif request.param == "postgres":
        b = PostgresBus(db_engine, TEST_DATABASE_URL)
    else:
        if not TEST_REDIS_URL:
            pytest.skip("TEST_REDIS_URL not set")
        b = RedisBus.from_url(TEST_REDIS_URL)
    yield b
    await b.aclose()


async def test_subscriber_receives_published_messages(bus: Bus) -> None:
    async with bus.subscribe("store:1") as messages:
        await asyncio.sleep(0.1)  # let redis/pg finish subscribing
        await bus.publish("store:1", {"type": "order.created", "n": 1})
        async with asyncio.timeout(3):
            assert await anext(messages) == {"type": "order.created", "n": 1}


async def test_channels_are_isolated(bus: Bus) -> None:
    async with bus.subscribe("store:a") as messages:
        await asyncio.sleep(0.1)
        await bus.publish("store:b", {"n": "other"})
        await bus.publish("store:a", {"n": "mine"})
        async with asyncio.timeout(3):
            assert await anext(messages) == {"n": "mine"}


async def test_two_subscribers_both_receive(bus: Bus) -> None:
    async with bus.subscribe("c") as one, bus.subscribe("c") as two:
        await asyncio.sleep(0.1)
        await bus.publish("c", {"x": 1})
        async with asyncio.timeout(3):
            assert await anext(one) == {"x": 1}
            assert await anext(two) == {"x": 1}
