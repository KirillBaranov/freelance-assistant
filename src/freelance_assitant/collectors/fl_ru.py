"""FL.ru RSS collector."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from html import unescape

import feedparser
import httpx

from freelance_assitant.collectors.base import BaseCollector, IngestScopeStats
from freelance_assitant.collectors.registry import CollectorRegistry
from freelance_assitant.config import FlRuFeedConfig, Settings, load_sources_config
from freelance_assitant.domain.enums import SourcePlatform
from freelance_assitant.domain.schemas import JobCandidateCreate
from freelance_assitant.storage.source_state import make_state_key, merge_recent_ids, utcnow_iso

logger = logging.getLogger("fa.collectors.fl_ru")

# Budget pattern: "(Бюджет: 7 500  ₽)" or "(Бюджет: 10000 руб.)"
BUDGET_RE = re.compile(
    r"\(Бюджет:\s*([\d\s]+)\s*(?:₽|&#8381;|руб\.?)\)",
    re.IGNORECASE,
)

# "(для всех)" marker — no budget
FOR_ALL_RE = re.compile(r"\(для всех\)", re.IGNORECASE)

RSS_URL = "https://www.fl.ru/rss/all.xml"
RECENT_IDS_LIMIT = 50

QUALITY_PRIORITY = {
    "low": 0,
    "medium": 1,
    "high": 2,
}

NOISE_HINTS = (
    "дизайн",
    "архитектур",
    "3d",
    "3д",
    "motion",
    "брендинг",
    "logo",
    "логотип",
    "визуал",
    "интерьер",
    "экстерьер",
    "иллюстрац",
    "лендинг на тильде",
)


@CollectorRegistry.register("fl_ru")
class FlRuCollector(BaseCollector):
    source = SourcePlatform.FL_RU

    def __init__(self, config: Settings, state_store=None):
        super().__init__(config, state_store=state_store)
        self._feeds = [feed for feed in load_sources_config().fl_ru.feeds if feed.enabled]
        if not self._feeds:
            self._feeds = [
                FlRuFeedConfig(
                    url=RSS_URL,
                    label="all",
                    source_quality="low",
                    source_bucket="broad_feed",
                )
            ]

    @property
    def poll_interval_seconds(self) -> int:
        return load_sources_config().fl_ru.poll_seconds or self.config.fl_poll_seconds

    async def collect(self) -> list[JobCandidateCreate]:
        self.reset_stats()
        deduped: dict[str, JobCandidateCreate] = {}
        async with httpx.AsyncClient(timeout=30) as client:
            for feed_cfg in self._feeds:
                state_key = make_state_key(self.source.value, feed_cfg.url)
                state = await self.state_store.get_json(state_key) or {}
                request_headers = {}
                if state.get("etag"):
                    request_headers["If-None-Match"] = state["etag"]
                if state.get("last_modified"):
                    request_headers["If-Modified-Since"] = state["last_modified"]

                try:
                    resp = await client.get(feed_cfg.url, headers=request_headers)
                    if resp.status_code == 304:
                        logger.info("[fl_ru:%s] not modified", feed_cfg.label)
                        self.last_run_stats.add_scope(
                            IngestScopeStats(label=feed_cfg.label, not_modified=1)
                        )
                        continue
                    resp.raise_for_status()
                except Exception:
                    logger.exception(f"Failed to fetch FL.ru feed: {feed_cfg.url}")
                    continue

                parsed = feedparser.parse(resp.text)
                known_ids = set(state.get("recent_source_ids", []))
                feed_ids: list[str] = []
                new_count = 0
                skipped_known = 0
                for entry in parsed.entries:
                    source_id = self._extract_source_id(
                        entry.get("link", ""),
                        entry.get("id", "") or entry.get("link", ""),
                    )
                    feed_ids.append(source_id)
                    if source_id in known_ids:
                        skipped_known += 1
                        break
                    try:
                        candidate = self._parse_entry(entry, feed_cfg)
                        if self._should_drop_noise(candidate):
                            continue
                        self._merge_candidate(deduped, candidate)
                        new_count += 1
                    except Exception:
                        logger.exception(
                            f"Failed to parse entry from {feed_cfg.label}: "
                            f"{getattr(entry, 'link', '?')}"
                        )

                await self.state_store.set_json(
                    state_key,
                    {
                        "etag": resp.headers.get("etag"),
                        "last_modified": resp.headers.get("last-modified"),
                        "recent_source_ids": merge_recent_ids(
                            feed_ids,
                            state.get("recent_source_ids", []),
                            limit=RECENT_IDS_LIMIT,
                        ),
                        "last_poll_at": utcnow_iso(),
                    },
                )
                logger.info(
                    "[fl_ru:%s] fetched=%s new=%s skipped_known=%s",
                    feed_cfg.label,
                    len(parsed.entries),
                    new_count,
                    skipped_known,
                )
                self.last_run_stats.add_scope(
                    IngestScopeStats(
                        label=feed_cfg.label,
                        fetched=len(parsed.entries),
                        new=new_count,
                        skipped_known=skipped_known,
                    )
                )

        candidates = list(deduped.values())
        logger.info(f"FL.ru: parsed {len(candidates)} candidates from {len(self._feeds)} feeds")
        return candidates

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                for feed_cfg in self._feeds:
                    resp = await client.head(feed_cfg.url)
                    if resp.status_code != 200:
                        return False
                return True
        except Exception:
            return False

    def _parse_entry(self, entry, feed_cfg) -> JobCandidateCreate:
        raw_title = unescape(entry.get("title", ""))
        link = entry.get("link", "")
        description = unescape(entry.get("description", "") or entry.get("summary", ""))
        category = unescape(entry.get("category", "") or feed_cfg.category_hint or "")
        guid = entry.get("id", "") or link

        # Extract budget from title
        budget_min, budget_max = self._extract_budget(raw_title)

        # Clean title (remove budget marker)
        title = BUDGET_RE.sub("", raw_title).strip()
        title = FOR_ALL_RE.sub("", title).strip()

        # Extract source_id from link
        source_id = self._extract_source_id(link, guid)

        return JobCandidateCreate(
            source=SourcePlatform.FL_RU,
            source_id=source_id,
            source_url=link,
            title=title,
            description=description,
            budget_min=budget_min,
            budget_max=budget_max,
            currency="RUB",
            category=category,
            raw_data={
                "source_quality": feed_cfg.source_quality,
                "source_bucket": feed_cfg.source_bucket,
                "category_hint": feed_cfg.category_hint,
                "feed_label": feed_cfg.label,
                "feed_quality": feed_cfg.source_quality,
                "matched_feeds": [feed_cfg.label],
                "ingest_variant": "rss_feed",
                "rss_title": raw_title,
                "rss_guid": guid,
                "rss_category": category,
                "rss_pubdate": entry.get("published", ""),
                "rss_url": feed_cfg.url,
            },
        )

    @staticmethod
    def _extract_budget(title: str) -> tuple[int | None, int | None]:
        match = BUDGET_RE.search(title)
        if not match:
            return None, None
        raw = match.group(1).replace(" ", "").replace("\xa0", "")
        try:
            budget = int(raw)
            return budget, budget
        except ValueError:
            return None, None

    @staticmethod
    def _extract_source_id(link: str, guid: str) -> str:
        # FL.ru links: https://www.fl.ru/projects/5500586/...
        match = re.search(r"/projects/(\d+)", link)
        if match:
            return match.group(1)
        # Fallback to guid or link hash
        return guid or link

    @staticmethod
    def _quality_priority(value: str | None) -> int:
        return QUALITY_PRIORITY.get((value or "medium").lower(), 1)

    def _should_drop_noise(self, candidate: JobCandidateCreate) -> bool:
        source_bucket = str(candidate.raw_data.get("source_bucket", "")).lower()
        if source_bucket != "broad_feed":
            return False

        text = " ".join(
            filter(
                None,
                [
                    candidate.title.lower(),
                    (candidate.description or "").lower(),
                    (candidate.category or "").lower(),
                    str(candidate.raw_data.get("category_hint", "")).lower(),
                ],
            )
        )
        return any(hint in text for hint in NOISE_HINTS)

    def _merge_candidate(
        self,
        deduped: dict[str, JobCandidateCreate],
        candidate: JobCandidateCreate,
    ) -> None:
        existing = deduped.get(candidate.source_id)
        if existing is None:
            deduped[candidate.source_id] = candidate
            return

        existing_feeds = list(existing.raw_data.get("matched_feeds", []))
        for label in candidate.raw_data.get("matched_feeds", []):
            if label not in existing_feeds:
                existing_feeds.append(label)
        existing.raw_data["matched_feeds"] = existing_feeds

        existing_quality = self._quality_priority(existing.raw_data.get("source_quality"))
        candidate_quality = self._quality_priority(candidate.raw_data.get("source_quality"))
        if candidate_quality <= existing_quality:
            return

        merged = deepcopy(candidate.raw_data)
        merged["matched_feeds"] = existing_feeds
        existing.title = candidate.title
        existing.description = candidate.description
        existing.budget_min = candidate.budget_min
        existing.budget_max = candidate.budget_max
        existing.category = candidate.category
        existing.raw_data = merged
