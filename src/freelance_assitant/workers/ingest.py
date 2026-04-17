"""Ingestion worker — polls sources and stores candidates."""

from __future__ import annotations

import logging

from freelance_assitant.collectors import fl_ru as _fl  # noqa: F401
from freelance_assitant.collectors import kwork as _kw  # noqa: F401
from freelance_assitant.collectors.registry import CollectorRegistry
from freelance_assitant.config import settings
from freelance_assitant.storage.repo import JobCandidateRepo
from freelance_assitant.storage.source_state import get_source_state_store, utcnow_iso

logger = logging.getLogger("fa.workers.ingest")


async def ingest_source(ctx: dict, source: str | None = None) -> int:
    """arq task: run collectors and store results.

    If source is given, run only that collector. Otherwise run all enabled.
    """
    session_factory = ctx["session_factory"]
    total_new = 0

    if source:
        collector_cls = CollectorRegistry.get(source)
        if not collector_cls:
            logger.error(f"Unknown source: {source}")
            return 0
        collectors = [collector_cls(settings)]
    else:
        collectors = CollectorRegistry.get_all_enabled(settings)

    state_store = get_source_state_store()
    for collector in collectors:
        try:
            candidates = await collector.collect()
            async with session_factory() as session:
                repo = JobCandidateRepo(session)
                new_count = await repo.upsert_batch(candidates)
            stats = collector.last_run_stats.to_dict()
            stats["inserted_new"] = new_count
            stats["recorded_at"] = utcnow_iso()
            await state_store.set_json(f"latest-ingest:{collector.source.value}", stats)
            total_new += new_count
            logger.info(
                f"[{collector.source}] Ingested {new_count} new / {len(candidates)} total "
                f"(fetched={collector.last_run_stats.fetched}, "
                f"skipped_known={collector.last_run_stats.skipped_known}, "
                f"not_modified={collector.last_run_stats.not_modified})"
            )
        except Exception:
            logger.exception(f"[{collector.source}] Ingestion failed")

    return total_new
