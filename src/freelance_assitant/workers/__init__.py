"""arq worker configuration."""

from __future__ import annotations

from arq import cron
from arq.worker import Worker

from freelance_assitant.storage.redis import get_redis_settings


async def startup(ctx: dict) -> None:
    from freelance_assitant.storage.database import async_session_factory, init_db

    await init_db()
    ctx["session_factory"] = async_session_factory


async def shutdown(ctx: dict) -> None:
    from freelance_assitant.storage.database import close_db

    await close_db()


class WorkerSettings:
    from freelance_assitant.workers.followup import followup_check
    from freelance_assitant.workers.ingest import ingest_source
    from freelance_assitant.workers.notify import notify_leads
    from freelance_assitant.workers.proposal import generate_proposal_task
    from freelance_assitant.workers.score import score_candidates
    from freelance_assitant.workers.status_check import check_job_statuses

    functions = [ingest_source, score_candidates, notify_leads, generate_proposal_task, followup_check, check_job_statuses]
    cron_jobs = [
        # FL.ru every 3 minutes
        cron(ingest_source, minute={0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48, 51, 54, 57}, second=0),
        # Score new candidates every minute
        cron(score_candidates, second=30),
        # Send Telegram notifications every minute (offset from scoring)
        cron(notify_leads, second=45),
        # Follow-up check every 30 minutes
        cron(followup_check, minute={0, 30}, second=15),
        # Status check every 30 minutes (offset from followup)
        cron(check_job_statuses, minute={15, 45}, second=0),
    ]
    redis_settings = get_redis_settings()
    on_startup = startup
    on_shutdown = shutdown


def create_worker() -> Worker:
    return Worker(**{
        "functions": WorkerSettings.functions,
        "cron_jobs": WorkerSettings.cron_jobs,
        "redis_settings": WorkerSettings.redis_settings,
        "on_startup": WorkerSettings.on_startup,
        "on_shutdown": WorkerSettings.on_shutdown,
    })
