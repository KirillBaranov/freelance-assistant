"""Base collector interface — all source adapters implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from freelance_assitant.config import Settings
    from freelance_assitant.domain.enums import SourcePlatform
    from freelance_assitant.domain.schemas import JobCandidateCreate
    from freelance_assitant.storage.source_state import SourceStateStore

from freelance_assitant.storage.source_state import get_source_state_store


class BaseCollector(ABC):
    """Abstract base for all source collectors.

    To add a new source:
    1. Create a new file in collectors/
    2. Subclass BaseCollector
    3. Decorate with @CollectorRegistry.register("source_name")
    4. Enable in config/sources.yaml
    """

    def __init__(self, config: Settings, state_store: SourceStateStore | None = None):
        self.config = config
        self.state_store = state_store or get_source_state_store()
        self.last_run_stats = IngestRunStats(source=self.source.value)

    @property
    @abstractmethod
    def source(self) -> SourcePlatform:
        """The source platform identifier."""

    @property
    @abstractmethod
    def poll_interval_seconds(self) -> int:
        """How often this collector should poll (in seconds)."""

    @abstractmethod
    async def collect(self) -> list[JobCandidateCreate]:
        """Fetch new jobs from the source. Returns normalized candidates."""

    async def health_check(self) -> bool:
        """Check if the source is reachable. Override for custom checks."""
        return True

    def reset_stats(self) -> None:
        self.last_run_stats = IngestRunStats(source=self.source.value)


@dataclass
class IngestScopeStats:
    label: str
    fetched: int = 0
    new: int = 0
    skipped_known: int = 0
    not_modified: int = 0


@dataclass
class IngestRunStats:
    source: str
    fetched: int = 0
    new: int = 0
    skipped_known: int = 0
    not_modified: int = 0
    scopes: list[IngestScopeStats] = field(default_factory=list)

    def add_scope(self, scope: IngestScopeStats) -> None:
        self.scopes.append(scope)
        self.fetched += scope.fetched
        self.new += scope.new
        self.skipped_known += scope.skipped_known
        self.not_modified += scope.not_modified

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "fetched": self.fetched,
            "new": self.new,
            "skipped_known": self.skipped_known,
            "not_modified": self.not_modified,
            "scopes": [
                {
                    "label": scope.label,
                    "fetched": scope.fetched,
                    "new": scope.new,
                    "skipped_known": scope.skipped_known,
                    "not_modified": scope.not_modified,
                }
                for scope in self.scopes
            ],
        }
