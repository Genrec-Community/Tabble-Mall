from mallt.core.errors import RateLimited
from mallt.core.kv import KV


async def hit(kv: KV, key: str, limit: int, window_s: int, code: str | None = None) -> None:
    """Count one event under ``key``; raise RateLimited past ``limit`` events per window."""
    count, ttl = await kv.incr_window(f"rl:{key}", window_s)
    if count > limit:
        raise RateLimited(retry_after=ttl, code=code)
