from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from freelance_assitant.status_checkers.base import BaseStatusChecker

_registry: dict[str, type[BaseStatusChecker]] = {}


class StatusCheckerRegistry:
    @staticmethod
    def register(source: str):
        def decorator(cls):
            _registry[source] = cls
            return cls
        return decorator

    @staticmethod
    def get(source: str) -> type[BaseStatusChecker] | None:
        return _registry.get(source)

    @staticmethod
    def all() -> dict[str, type[BaseStatusChecker]]:
        return dict(_registry)
