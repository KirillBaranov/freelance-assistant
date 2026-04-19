"""Status check worker — periodically checks if active jobs are still open.

Loads config from config/status_check.yaml.
For each active candidate, runs the platform-specific StatusChecker.
Closes (archives) jobs where the platform signals executor selected / deleted / expired.
"""

from __future__ import annotations

import logging
from freelance_assitant.config import CONFIG_DIR

import yaml
from pathlib import Path
from sqlalchemy import select

from freelance_assitant.domain.enums import JobStatus, SourcePlatform
from freelance_assitant.status_checkers import fl_ru, workspace  # noqa: F401 — register checkers
from freelance_assitant.status_checkers.registry import StatusCheckerRegistry
from freelance_assitant.storage.models import JobCandidate
from freelance_assitant.storage.repo import JobCandidateRepo

logger = logging.getLogger("fa.workers.status_check")

# Statuses worth checking — no point checking archived/won/lost
ACTIVE_STATUSES = {
    JobStatus.NEW,
    JobStatus.SHORTLISTED,
    JobStatus.DRAFT_READY,
    JobStatus.APPROVED,
    JobStatus.APPLIED,
    JobStatus.FOLLOWUP_DUE,
}

_CONFIG_PATH = CONFIG_DIR / "status_check.yaml"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


async def check_job_statuses(ctx: dict) -> int:
    """arq task: close jobs that are no longer open on the platform."""
    cfg = _load_config().get("status_check", {})
    if not cfg.get("enabled", True):
        return 0

    platform_configs: dict = cfg.get("platforms", {})
    check_statuses: list[str] = cfg.get("check_statuses", [s.value for s in ACTIVE_STATUSES])
    batch_size: int = cfg.get("batch_size", 30)

    session_factory = ctx["session_factory"]
    closed = 0

    async with session_factory() as session:
        repo = JobCandidateRepo(session)

        stmt = (
            select(JobCandidate)
            .where(JobCandidate.status.in_(check_statuses))
            .where(JobCandidate.source_url.isnot(None))
            .order_by(JobCandidate.updated_at.asc())  # oldest checked first
            .limit(batch_size)
        )
        result = await session.execute(stmt)
        candidates = result.scalars().all()

        for candidate in candidates:
            source = candidate.source
            checker_cls = StatusCheckerRegistry.get(source)
            if checker_cls is None:
                continue

            platform_cfg = platform_configs.get(source, {})
            if not platform_cfg.get("enabled", True):
                continue

            checker = checker_cls(config=platform_cfg)
            try:
                result = await checker.check(candidate)
            except Exception as e:
                logger.warning("Status check error for %s (%s): %s", candidate.id, source, e)
                continue

            if result.should_close:
                await repo.update_status(candidate.id, JobStatus.ARCHIVED)
                logger.info(
                    "Closed [%s] %s — reason: %s",
                    source,
                    candidate.title[:60],
                    result.reason,
                )
                closed += 1

    if closed:
        logger.info("Status check: closed %d stale jobs", closed)
    return closed
