"""Collector registry — auto-discovery of source adapters.

Add a new source by creating a file in collectors/ and decorating the class:

    @CollectorRegistry.register("my_source")
    class MyCollector(BaseCollector):
        ...

Then add "my_source" to config/sources.yaml `enabled: true` or FA_ENABLED_SOURCES env var.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from freelance_assitant.collectors.base import BaseCollector
    from freelance_assitant.config import Settings

logger = logging.getLogger("fa.collectors")


class CollectorRegistry:
    _collectors: dict[str, type[BaseCollector]] = {}

    @classmethod
    def register(cls, source: str):
        """Decorator to register a collector class for a source."""

        def decorator(klass: type[BaseCollector]) -> type[BaseCollector]:
            cls._collectors[source] = klass
            logger.debug(f"Registered collector: {source} -> {klass.__name__}")
            return klass

        return decorator

    @classmethod
    def get(cls, source: str) -> type[BaseCollector] | None:
        return cls._collectors.get(source)

    @classmethod
    def get_all_enabled(cls, config: Settings) -> list[BaseCollector]:
        """Instantiate all collectors whose source is in config.enabled_sources."""
        result: list[BaseCollector] = []
        for source_name in config.enabled_sources:
            klass = cls._collectors.get(source_name)
            if klass is None:
                logger.warning(f"Source '{source_name}' enabled but no collector registered")
                continue
            result.append(klass(config))
        return result

    @classmethod
    def list_registered(cls) -> list[str]:
        return list(cls._collectors.keys())
