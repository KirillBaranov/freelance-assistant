from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from freelance_assitant.domain.enums import JobStatus, LeadTier
from freelance_assitant.domain.schemas import JobCandidateCreate, JobCandidateRead
from freelance_assitant.storage.models import JobCandidate


class JobCandidateRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_batch(self, candidates: list[JobCandidateCreate]) -> int:
        """Insert new candidates, skip duplicates. Returns count of new rows."""
        if not candidates:
            return 0
        new_count = 0
        for c in candidates:
            stmt = (
                pg_insert(JobCandidate)
                .values(**c.model_dump())
                .on_conflict_do_nothing(index_elements=["source", "source_id"])
            )
            result = await self.session.execute(stmt)
            if result.rowcount > 0:
                new_count += 1
        await self.session.commit()
        return new_count

    async def get_by_status(
        self, status: JobStatus | str, limit: int = 50
    ) -> list[JobCandidateRead]:
        stmt = (
            select(JobCandidate)
            .where(JobCandidate.status == status)
            .order_by(JobCandidate.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [JobCandidateRead.model_validate(r) for r in rows]

    async def get_by_id(self, candidate_id: uuid.UUID) -> JobCandidateRead | None:
        stmt = select(JobCandidate).where(JobCandidate.id == candidate_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return JobCandidateRead.model_validate(row) if row else None

    async def update_score(
        self,
        candidate_id: uuid.UUID,
        score: float,
        tier: LeadTier,
        details: dict[str, Any],
    ) -> None:
        stmt = (
            update(JobCandidate)
            .where(JobCandidate.id == candidate_id)
            .values(score=score, tier=tier.value, score_details=details)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def update_status(self, candidate_id: uuid.UUID, status: JobStatus | str) -> None:
        stmt = (
            update(JobCandidate)
            .where(JobCandidate.id == candidate_id)
            .values(status=status)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def update_proposal(self, candidate_id: uuid.UUID, draft: str) -> None:
        stmt = (
            update(JobCandidate)
            .where(JobCandidate.id == candidate_id)
            .values(proposal_draft=draft, status=JobStatus.DRAFT_READY)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def mark_notified(self, candidate_id: uuid.UUID) -> None:
        stmt = (
            update(JobCandidate)
            .where(JobCandidate.id == candidate_id)
            .values(notified_at=datetime.now(tz=__import__("zoneinfo").ZoneInfo("UTC")))
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_unscored(self, limit: int = 50) -> list[JobCandidateRead]:
        stmt = (
            select(JobCandidate)
            .where(JobCandidate.status == JobStatus.NEW, JobCandidate.score.is_(None))
            .order_by(JobCandidate.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [JobCandidateRead.model_validate(r) for r in rows]

    async def get_shortlisted_unnotified(self, limit: int = 20) -> list[JobCandidateRead]:
        stmt = (
            select(JobCandidate)
            .where(
                JobCandidate.status == JobStatus.SHORTLISTED,
                JobCandidate.notified_at.is_(None),
            )
            .order_by(JobCandidate.score.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [JobCandidateRead.model_validate(r) for r in rows]
