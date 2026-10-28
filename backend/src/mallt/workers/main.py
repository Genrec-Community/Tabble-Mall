"""ARQ worker. Only used when REDIS_URL is set; without Redis jobs run inline in the API."""

from typing import Any

from arq.connections import RedisSettings

from mallt.core.config import get_settings


async def heartbeat(ctx: dict[str, Any]) -> str:
    return "ok"


def _redis_settings() -> RedisSettings:
    url = get_settings().redis_url
    return RedisSettings.from_dsn(url) if url else RedisSettings()


class WorkerSettings:
    functions = [heartbeat]
    cron_jobs: list[Any] = []
    redis_settings = _redis_settings()
