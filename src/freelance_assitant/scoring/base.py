"""Base scorer interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from freelance_assitant.domain.schemas import JobCandidateRead


class BaseScorer(ABC):
    """All scorers implement this interface.

    To add a new scorer:
    1. Subclass BaseScorer
    2. Implement `name` and `evaluate()`
    3. Add to scoring engine's scorer list (via config or explicit registration)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this scorer (used in score_details JSON)."""

    @abstractmethod
    async def evaluate(self, candidate: JobCandidateRead, profile: dict) -> float:
        """Score a candidate. Returns 0.0 to 1.0."""
