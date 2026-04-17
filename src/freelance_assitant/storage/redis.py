from __future__ import annotations

from arq.connections import RedisSettings

from freelance_assitant.config import settings


def get_redis_settings() -> RedisSettings:
    """Parse redis URL into arq RedisSettings."""
    from urllib.parse import urlparse

    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password,
    )
