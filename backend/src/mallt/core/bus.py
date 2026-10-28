"""Tiny pub/sub for live updates. Redis when ``REDIS_URL`` is set, else Postgres LISTEN/NOTIFY.

Messages are small JSON dicts (ids and statuses, never personal data); subscribers re-fetch
what they need over the normal authorised API. Delivery is best effort: a missed message is
repaired by the client re-fetching when it reconnects.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Protocol

import asyncpg
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from mallt.core.db import normalize_database_url

if TYPE_CHECKING:
    from mallt.core.config import Settings

log = logging.getLogger(__name__)
PG_CHANNEL = "mallt_events"
PG_MAX_PAYLOAD = 7000


class Bus(Protocol):
    async def publish(self, channel: str, message: dict[str, Any]) -> None: ...

    def subscribe(
        self, channel: str
    ) -> contextlib.AbstractAsyncContextManager[AsyncIterator[dict[str, Any]]]: ...

    async def aclose(self) -> None: ...


class MemoryBus:
    """In-process fan-out. Also the local delivery stage of the Postgres bus."""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    def deliver(self, channel: str, message: dict[str, Any]) -> None:
        for queue in list(self._subs.get(channel, ())):
            queue.put_nowait(message)

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        self.deliver(channel, message)

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subs.setdefault(channel, set()).add(queue)

        async def messages() -> AsyncIterator[dict[str, Any]]:
            while True:
                yield await queue.get()

        try:
            yield messages()
        finally:
            subs = self._subs.get(channel)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    del self._subs[channel]

    async def aclose(self) -> None:
        self._subs.clear()


class RedisBus:
    prefix = "mallt:bus:"

    def __init__(self, client: Redis) -> None:
        self.r = client

    @classmethod
    def from_url(cls, url: str) -> "RedisBus":
        return cls(Redis.from_url(url, decode_responses=True))

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        await self.r.publish(self.prefix + channel, json.dumps(message))

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        pubsub = self.r.pubsub()
        await pubsub.subscribe(self.prefix + channel)

        async def messages() -> AsyncIterator[dict[str, Any]]:
            async for item in pubsub.listen():
                if item["type"] == "message":
                    yield json.loads(item["data"])

        try:
            yield messages()
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()  # type: ignore[no-untyped-call]

    async def aclose(self) -> None:
        await self.r.aclose()


class PostgresBus:
    """NOTIFY to publish; one LISTEN connection per process feeds a local MemoryBus."""

    def __init__(self, engine: AsyncEngine, database_url: str) -> None:
        self.engine = engine
        url, args = normalize_database_url(database_url)
        self._dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        self._ssl = args.get("ssl")
        self._local = MemoryBus()
        self._conn: asyncpg.Connection | None = None
        self._lock = asyncio.Lock()

    async def _ensure_listener(self) -> None:
        async with self._lock:
            if self._conn is not None and not self._conn.is_closed():
                return
            self._conn = await asyncpg.connect(self._dsn, ssl=self._ssl)
            await self._conn.add_listener(PG_CHANNEL, self._on_notify)

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            data = json.loads(payload)
            self._local.deliver(data["c"], data["m"])
        except (ValueError, KeyError):
            log.warning("bad bus payload")

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        payload = json.dumps({"c": channel, "m": message})
        if len(payload) > PG_MAX_PAYLOAD:
            log.warning("bus message too large, dropped")
            return
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT pg_notify(:ch, :p)"), {"ch": PG_CHANNEL, "p": payload})
            await conn.commit()

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[AsyncIterator[dict[str, Any]]]:
        await self._ensure_listener()
        async with self._local.subscribe(channel) as messages:
            yield messages

    async def aclose(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            await self._conn.close()
        await self._local.aclose()


def make_bus(settings: "Settings", engine: AsyncEngine) -> Bus:
    if settings.redis_url:
        return RedisBus.from_url(settings.redis_url)
    return PostgresBus(engine, settings.database_url)
