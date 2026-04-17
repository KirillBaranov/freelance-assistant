"""Scoring worker — scores unscored candidates."""

from __future__ import annotations

import logging

from freelance_assitant.domain.enums import JobStatus, LeadTier
from freelance_assitant.scoring.engine import ScoringEngine
from freelance_assitant.storage.repo import JobCandidateRepo

logger = logging.getLogger("fa.workers.score")

_engine: ScoringEngine | None = None


def _get_engine() -> ScoringEngine:
    global _engine
    if _engine is None:
        _engine = ScoringEngine()
    return _engine


async def score_candidates(ctx: dict) -> int:
    """arq task: score unscored candidates and classify them."""
    session_factory = ctx["session_factory"]
    engine = _get_engine()
    scored_count = 0

    async with session_factory() as session:
        repo = JobCandidateRepo(session)
        unscored = await repo.get_unscored(limit=50)

        for candidate in unscored:
            try:
                result = await engine.score(candidate)
                await repo.update_score(
                    candidate.id,
                    score=result.score,
                    tier=result.tier,
                    details=result.details,
                )

                # Shortlist-worthy leads get promoted for notification.
                if result.shortlist:
                    await repo.update_status(candidate.id, JobStatus.SHORTLISTED)
                elif result.tier == LeadTier.C or result.details.get("hard_reject"):
                    await repo.update_status(candidate.id, JobStatus.ARCHIVED)
                # B-leads stay in "new" status, visible in backlog

                scored_count += 1
                logger.info(
                    f"Scored '{candidate.title[:50]}': {result.score:.2f} "
                    f"({result.tier}, shortlist={result.shortlist})"
                )
            except Exception:
                logger.exception(f"Failed to score candidate {candidate.id}")

    return scored_count
