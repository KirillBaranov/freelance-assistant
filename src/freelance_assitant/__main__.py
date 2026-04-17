"""CLI entrypoint: `python -m freelance_assitant` or `fa`."""

from __future__ import annotations

import asyncio
import logging

import click
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fa")


@click.group()
def cli() -> None:
    """Freelance Assistant — personal lead-generation system."""


@cli.command()
@click.option("--host", default="0.0.0.0", help="API bind host")
@click.option("--port", default=8000, type=int, help="API bind port")
def run(host: str, port: int) -> None:
    """Run all services: FastAPI + arq worker + Telegram bot."""
    asyncio.run(_run_all(host, port))


@cli.command()
def migrate() -> None:
    """Run database migrations (alembic upgrade head)."""
    from alembic.config import Config

    from alembic import command
    from freelance_assitant.config import PROJECT_ROOT

    alembic_cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    click.echo("Migrations applied.")


@cli.command()
def ingest() -> None:
    """Run a single ingestion cycle for all enabled sources."""
    asyncio.run(_run_ingest())


@cli.command()
@click.option("--limit", default=100, type=int, help="Max candidates to rescore")
@click.option(
    "--missing-insights-only",
    is_flag=True,
    help="Rescore only records that miss shortlist/decision fields",
)
def rescore(limit: int, missing_insights_only: bool) -> None:
    """Recompute scores for existing candidates and backfill new insight fields."""
    asyncio.run(_run_rescore(limit=limit, missing_insights_only=missing_insights_only))


async def _run_all(host: str, port: int) -> None:
    from freelance_assitant.storage.database import close_db, init_db

    await init_db()
    logger.info("Database connected")

    tasks: list[asyncio.Task] = []

    # arq worker
    try:
        from freelance_assitant.workers import create_worker

        worker = create_worker()
        tasks.append(asyncio.create_task(worker.async_run()))
        logger.info("arq worker started")
    except Exception:
        logger.exception("Failed to start arq worker")

    # Telegram bot
    try:
        from freelance_assitant.bot.setup import start_bot

        tasks.append(asyncio.create_task(start_bot()))
        logger.info("Telegram bot started")
    except Exception:
        logger.exception("Failed to start Telegram bot")

    # FastAPI (uvicorn) — runs in the main coroutine
    config = uvicorn.Config(
        "freelance_assitant.api.app:app",
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        for t in tasks:
            t.cancel()
        await close_db()
        logger.info("Shutdown complete")


async def _run_ingest() -> None:
    # Import collectors so they register themselves
    from freelance_assitant.collectors import fl_ru as _fl  # noqa: F401
    from freelance_assitant.collectors import kwork as _kw  # noqa: F401
    from freelance_assitant.collectors import workspace as _ws  # noqa: F401
    from freelance_assitant.collectors.registry import CollectorRegistry
    from freelance_assitant.config import settings
    from freelance_assitant.storage.database import async_session_factory, close_db, init_db
    from freelance_assitant.storage.repo import JobCandidateRepo
    from freelance_assitant.storage.source_state import get_source_state_store, utcnow_iso

    await init_db()
    collectors = CollectorRegistry.get_all_enabled(settings)
    state_store = get_source_state_store()

    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        for collector in collectors:
            try:
                candidates = await collector.collect()
                new_count = await repo.upsert_batch(candidates)
                stats = collector.last_run_stats.to_dict()
                stats["inserted_new"] = new_count
                stats["recorded_at"] = utcnow_iso()
                await state_store.set_json(f"latest-ingest:{collector.source.value}", stats)
                logger.info(
                    f"[{collector.source}] Ingested {new_count} new / {len(candidates)} total "
                    f"(fetched={collector.last_run_stats.fetched}, "
                    f"skipped_known={collector.last_run_stats.skipped_known}, "
                    f"not_modified={collector.last_run_stats.not_modified})"
                )
            except Exception:
                logger.exception(f"[{collector.source}] Ingestion failed")

    await close_db()


async def _run_rescore(limit: int, missing_insights_only: bool) -> None:
    from sqlalchemy import or_, select

    from freelance_assitant.domain.enums import JobStatus, LeadTier
    from freelance_assitant.domain.schemas import JobCandidateRead
    from freelance_assitant.scoring.engine import ScoringEngine
    from freelance_assitant.storage.database import async_session_factory, close_db, init_db
    from freelance_assitant.storage.models import JobCandidate
    from freelance_assitant.storage.repo import JobCandidateRepo

    await init_db()
    engine = ScoringEngine()
    updated = 0

    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        stmt = (
            select(JobCandidate)
            .where(JobCandidate.score.is_not(None))
            .order_by(JobCandidate.updated_at.desc())
            .limit(limit)
        )
        if missing_insights_only:
            stmt = stmt.where(
                or_(
                    JobCandidate.score_details.is_(None),
                    JobCandidate.score_details["shortlist_fit"].astext.is_(None),
                    JobCandidate.score_details["decision_enrichment"].astext.is_(None),
                )
            )

        rows = (await session.execute(stmt)).scalars().all()

        for row in rows:
            candidate = JobCandidateRead.model_validate(row)
            result = await engine.score(candidate)
            await repo.update_score(
                candidate.id,
                score=result.score,
                tier=result.tier,
                details=result.details,
            )

            if result.shortlist:
                await repo.update_status(candidate.id, JobStatus.SHORTLISTED)
            elif result.tier == LeadTier.C or result.details.get("hard_reject"):
                await repo.update_status(candidate.id, JobStatus.ARCHIVED)

            updated += 1
            logger.info(
                "Rescored '%s': %.2f (%s, shortlist=%s)",
                candidate.title[:60],
                result.score,
                result.tier,
                result.shortlist,
            )

    await close_db()
    click.echo(f"Rescored {updated} candidates.")


if __name__ == "__main__":
    cli()
