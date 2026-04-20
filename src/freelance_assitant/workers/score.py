"""Scoring worker — scores candidates per user profile."""

from __future__ import annotations

import logging

from freelance_assitant.config import load_users
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
    """arq task: score unscored candidates for each registered user."""
    session_factory = ctx["session_factory"]
    engine = _get_engine()
    users = load_users()

    if not users:
        # Fallback: single-user mode (legacy)
        return await _score_single_user(ctx, engine)

    scored_total = 0
    for user in users:
        profile = user.profile.model_dump()
        user_id = str(user.telegram_id)

        async with session_factory() as session:
            repo = JobCandidateRepo(session)
            unscored = await repo.get_candidates_without_user_state(user_id, limit=50)

        for candidate in unscored:
            try:
                result = await engine.score(candidate, profile)

                status = JobStatus.NEW
                if result.shortlist and not result.details.get("hard_reject"):
                    status = JobStatus.SHORTLISTED
                elif result.tier == LeadTier.C or result.details.get("hard_reject"):
                    status = JobStatus.ARCHIVED

                async with session_factory() as session:
                    repo = JobCandidateRepo(session)
                    await repo.upsert_user_job_state(
                        user_id=user_id,
                        candidate_id=candidate.id,
                        score=result.score,
                        tier=result.tier,
                        details=result.details,
                        status=status,
                    )

                scored_total += 1
                logger.info(
                    f"[{user.name}] Scored '{candidate.title[:50]}': "
                    f"{result.score:.2f} ({result.tier}, shortlist={result.shortlist})"
                )
            except Exception:
                logger.exception(f"[{user.name}] Failed to score candidate {candidate.id}")

    return scored_total


async def _score_single_user(ctx: dict, engine: ScoringEngine) -> int:
    """Legacy single-user scoring path (no users/ config)."""
    session_factory = ctx["session_factory"]
    scored_count = 0

    async with session_factory() as session:
        repo = JobCandidateRepo(session)
        unscored = await repo.get_unscored(limit=50)

        for candidate in unscored:
            try:
                result = await engine.score(candidate)
                await repo.update_score(candidate.id, result.score, result.tier, result.details)
                if result.shortlist:
                    await repo.update_status(candidate.id, JobStatus.SHORTLISTED)
                elif result.tier == LeadTier.C or result.details.get("hard_reject"):
                    await repo.update_status(candidate.id, JobStatus.ARCHIVED)
                scored_count += 1
            except Exception:
                logger.exception(f"Failed to score candidate {candidate.id}")

    return scored_count
