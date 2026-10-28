"""Small key-value store used for OTPs, rate limits and short-lived caches.

Redis is optional. With ``REDIS_URL`` set we use Redis; otherwise we fall back to a Postgres
table, which is correct across several API containers (just a bit more DB load). The fallback
runs in its own transactions so counters survive a request rollback (e.g. a 429 response).
"""

import random
from typing import TYPE_CHECKING, Protocol

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

if TYPE_CHECKING:
    from fastapi import Request

    from mallt.core.config import Settings


class KV(Protocol):
    async def incr_window(self, key: str, window_s: int) -> tuple[int, int]:
        """Fixed-window counter. Returns (count_in_window, seconds_until_window_ends)."""

    async def set(self, key: str, value: str, ttl_s: int) -> None: ...

    async def get(self, key: str) -> str | None: ...

    async def delete(self, key: str) -> None: ...

    async def ping(self) -> None: ...

    async def flush(self) -> None:
        """Remove every key. Test helper."""

    async def aclose(self) -> None: ...


class RedisKV:
    prefix = "mallt:"

    def __init__(self, client: Redis) -> None:
        self.r = client

    @classmethod
    def from_url(cls, url: str) -> "RedisKV":
        return cls(Redis.from_url(url, decode_responses=True))

    async def incr_window(self, key: str, window_s: int) -> tuple[int, int]:
        k = self.prefix + key
        pipe = self.r.pipeline()
        pipe.incr(k)
        pipe.expire(k, window_s, nx=True)
        pipe.ttl(k)
        count, _, ttl = await pipe.execute()
        return int(count), max(int(ttl), 1)

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        await self.r.set(self.prefix + key, value, ex=ttl_s)

    async def get(self, key: str) -> str | None:
        value: str | None = await self.r.get(self.prefix + key)
        return value

    async def delete(self, key: str) -> None:
        await self.r.delete(self.prefix + key)

    async def ping(self) -> None:
        await self.r.ping()

    async def flush(self) -> None:
        keys = [k async for k in self.r.scan_iter(match=self.prefix + "*")]
        if keys:
            await self.r.delete(*keys)

    async def aclose(self) -> None:
        await self.r.aclose()


class PostgresKV:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def incr_window(self, key: str, window_s: int) -> tuple[int, int]:
        stmt = text(
            """
            INSERT INTO kv_store (key, counter, expires_at)
            VALUES (:k, 1, now() + make_interval(secs => :w))
            ON CONFLICT (key) DO UPDATE SET
              counter = CASE WHEN kv_store.expires_at <= now() THEN 1
                             ELSE kv_store.counter + 1 END,
              expires_at = CASE WHEN kv_store.expires_at <= now()
                                THEN now() + make_interval(secs => :w)
                                ELSE kv_store.expires_at END
            RETURNING counter,
              GREATEST(1, CEIL(EXTRACT(EPOCH FROM (expires_at - now()))))::int
            """
        )
        async with self.engine.begin() as conn:
            row = (await conn.execute(stmt, {"k": key, "w": window_s})).one()
        await self._maybe_purge()
        return int(row[0]), int(row[1])

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        stmt = text(
            """
            INSERT INTO kv_store (key, value, counter, expires_at)
            VALUES (:k, :v, 0, now() + make_interval(secs => :t))
            ON CONFLICT (key) DO UPDATE SET
              value = :v, counter = 0, expires_at = now() + make_interval(secs => :t)
            """
        )
        async with self.engine.begin() as conn:
            await conn.execute(stmt, {"k": key, "v": value, "t": ttl_s})
        await self._maybe_purge()

    async def get(self, key: str) -> str | None:
        stmt = text("SELECT value FROM kv_store WHERE key = :k AND expires_at > now()")
        async with self.engine.connect() as conn:
            return (await conn.execute(stmt, {"k": key})).scalar_one_or_none()

    async def delete(self, key: str) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM kv_store WHERE key = :k"), {"k": key})

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def flush(self) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM kv_store"))

    async def purge_expired(self) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM kv_store WHERE expires_at <= now()"))

    async def _maybe_purge(self) -> None:
        if random.random() < 0.01:  # noqa: S311 - not security related
            await self.purge_expired()

    async def aclose(self) -> None:
        return None


def make_kv(settings: "Settings", engine: AsyncEngine) -> KV:
    if settings.redis_url:
        return RedisKV.from_url(settings.redis_url)
    return PostgresKV(engine)


def get_kv(request: "Request") -> KV:
    kv: KV = request.app.state.kv
    return kv
