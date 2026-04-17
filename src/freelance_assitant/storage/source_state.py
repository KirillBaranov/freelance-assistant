from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis, from_url

from freelance_assitant.config import settings

logger = logging.getLogger("fa.source_state")

RECENT_IDS_LIMIT = 100


class SourceStateStore:
    """Redis-backed state store for incremental polling."""

    def __init__(self, redis_client: Redis | None = None, prefix: str = "fa:source-state"):
        self._redis = redis_client
        self._prefix = prefix

    def _client(self) -> Redis:
        if self._redis is None:
            self._redis = from_url(settings.redis_url, decode_responses=True)
        return self._redis

    def namespaced(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get_json(self, key: str) -> dict[str, Any] | None:
        try:
            data = await self._client().get(self.namespaced(key))
        except Exception:
            logger.exception("Failed to load source state for key=%s", key)
            return None

        if not data:
            return None

        try:
            import json

            parsed = json.loads(data)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            logger.exception("Failed to decode source state for key=%s", key)
            return None

    async def set_json(self, key: str, value: dict[str, Any]) -> None:
        try:
            import json

            await self._client().set(self.namespaced(key), json.dumps(value, ensure_ascii=False))
        except Exception:
            logger.exception("Failed to persist source state for key=%s", key)

    async def get_latest_ingest_stats(self) -> list[dict[str, Any]]:
        try:
            keys = await self._client().keys(self.namespaced("latest-ingest:*"))
        except Exception:
            logger.exception("Failed to list latest ingest stats")
            return []

        result: list[dict[str, Any]] = []
        for key in sorted(keys):
            short_key = key.removeprefix(f"{self._prefix}:")
            data = await self.get_json(short_key)
            if data:
                result.append(data)
        return result


class MemorySourceStateStore(SourceStateStore):
    """In-memory state store for tests."""

    def __init__(self):
        self._data: dict[str, dict[str, Any]] = {}
        super().__init__(redis_client=None, prefix="memory")

    async def get_json(self, key: str) -> dict[str, Any] | None:
        value = self._data.get(key)
        return dict(value) if value else None

    async def set_json(self, key: str, value: dict[str, Any]) -> None:
        self._data[key] = dict(value)

    async def get_latest_ingest_stats(self) -> list[dict[str, Any]]:
        result = []
        for key in sorted(self._data):
            if key.startswith("latest-ingest:"):
                result.append(dict(self._data[key]))
        return result


_store: SourceStateStore | None = None


def get_source_state_store() -> SourceStateStore:
    global _store
    if _store is None:
        _store = SourceStateStore()
    return _store


def make_state_key(source: str, scope: str) -> str:
    digest = hashlib.sha1(scope.encode("utf-8")).hexdigest()[:12]
    return f"{source}:{digest}"


def merge_recent_ids(
    current_ids: list[str],
    previous_ids: list[str],
    limit: int = RECENT_IDS_LIMIT,
) -> list[str]:
    merged: list[str] = []
    for source_id in [*current_ids, *previous_ids]:
        if not source_id or source_id in merged:
            continue
        merged.append(source_id)
        if len(merged) >= limit:
            break
    return merged


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()
