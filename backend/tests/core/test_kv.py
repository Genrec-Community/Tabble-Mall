import asyncio

import pytest

from mallt.core.errors import RateLimited
from mallt.core.kv import KV
from mallt.core.ratelimit import hit


async def test_hit_allows_up_to_limit_then_429(kv: KV) -> None:
    for _ in range(3):
        await hit(kv, "t:a", limit=3, window_s=60)
    with pytest.raises(RateLimited) as e:
        await hit(kv, "t:a", limit=3, window_s=60)
    assert 0 < e.value.retry_after <= 60
    assert e.value.headers() == {"Retry-After": str(e.value.retry_after)}


async def test_keys_are_independent(kv: KV) -> None:
    for _ in range(3):
        await hit(kv, "t:a", 3, 60)
    await hit(kv, "t:b", 3, 60)  # does not raise


async def test_window_resets_after_expiry(kv: KV) -> None:
    await hit(kv, "t:w", 1, 1)
    with pytest.raises(RateLimited):
        await hit(kv, "t:w", 1, 1)
    await asyncio.sleep(1.2)
    await hit(kv, "t:w", 1, 1)


async def test_set_get_delete(kv: KV) -> None:
    assert await kv.get("k") is None
    await kv.set("k", "v", ttl_s=60)
    assert await kv.get("k") == "v"
    await kv.set("k", "v2", ttl_s=60)
    assert await kv.get("k") == "v2"
    await kv.delete("k")
    assert await kv.get("k") is None


async def test_set_expires(kv: KV) -> None:
    await kv.set("e", "v", ttl_s=1)
    assert await kv.get("e") == "v"
    await asyncio.sleep(1.2)
    assert await kv.get("e") is None


async def test_ping(kv: KV) -> None:
    await kv.ping()
