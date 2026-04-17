"""Base interface for job status checkers.

To add a new platform:
1. Create a file in status_checkers/
2. Subclass BaseStatusChecker
3. Decorate with @StatusCheckerRegistry.register("source_name")
4. Enable in config/status_check.yaml
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from freelance_assitant.storage.models import JobCandidate


class CloseReason(StrEnum):
    EXECUTOR_SELECTED = "executor_selected"
    CLOSED = "closed"
    DELETED = "deleted"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"


@dataclass
class CheckResult:
    should_close: bool
    reason: CloseReason | None = None
    raw: str = ""  # snippet from page for debugging


class BaseStatusChecker(ABC):
    """Abstract base for all platform status checkers."""

    @property
    @abstractmethod
    def source(self) -> str:
        """SourcePlatform value this checker handles."""

    @abstractmethod
    async def check(self, candidate: JobCandidate) -> CheckResult:
        """Check whether the job is still open.

        Returns CheckResult(should_close=True) if the job should be archived.
        """
