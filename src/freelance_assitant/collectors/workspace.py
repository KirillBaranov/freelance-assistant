"""Workspace.ru tenders collector."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from freelance_assitant.collectors.base import BaseCollector, IngestScopeStats
from freelance_assitant.collectors.registry import CollectorRegistry
from freelance_assitant.config import Settings, WorkspaceSectionConfig, load_sources_config
from freelance_assitant.domain.enums import SourcePlatform
from freelance_assitant.domain.schemas import JobCandidateCreate
from freelance_assitant.storage.source_state import make_state_key, merge_recent_ids, utcnow_iso

logger = logging.getLogger("fa.collectors.workspace")

BASE_URL = "https://workspace.ru"
RECENT_IDS_LIMIT = 100
KNOWN_STREAK_STOP = 3
CARD_LIMIT_PER_SECTION = 15
DETAIL_FETCH_LIMIT = 8
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
ID_RE = re.compile(r"-(\d+)/?$")


@CollectorRegistry.register("workspace")
class WorkspaceCollector(BaseCollector):
    source = SourcePlatform.WORKSPACE

    def __init__(self, config: Settings, state_store=None):
        super().__init__(config, state_store=state_store)
        self._sections = [section for section in load_sources_config().workspace.sections if section.enabled]

    @property
    def poll_interval_seconds(self) -> int:
        return load_sources_config().workspace.poll_seconds or self.config.workspace_poll_seconds

    async def collect(self) -> list[JobCandidateCreate]:
        self.reset_stats()
        sections = self._sections or []
        if not sections:
            return []

        candidates: list[JobCandidateCreate] = []
        async with httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
            follow_redirects=True,
        ) as client:
            for section in sections:
                try:
                    section_candidates = await self._collect_section(client, section)
                    candidates.extend(section_candidates)
                except Exception:
                    logger.exception("Failed to collect Workspace section %s", section.label)

        logger.info("Workspace: parsed %s candidates", len(candidates))
        return candidates

    async def _collect_section(
        self,
        client: httpx.AsyncClient,
        section: WorkspaceSectionConfig,
    ) -> list[JobCandidateCreate]:
        state_key = make_state_key(self.source.value, section.url)
        state = await self.state_store.get_json(state_key) or {}
        resp = await client.get(section.url)
        resp.raise_for_status()

        cards = self._extract_cards(resp.text, section)[:CARD_LIMIT_PER_SECTION]
        known_ids = set(state.get("recent_source_ids", []))
        recent_ids = [card["source_id"] for card in cards]

        new_cards: list[dict[str, Any]] = []
        known_streak = 0
        for card in cards:
            if card["source_id"] in known_ids:
                known_streak += 1
                if known_streak >= KNOWN_STREAK_STOP:
                    break
                continue
            known_streak = 0
            new_cards.append(card)

        candidates: list[JobCandidateCreate] = []
        for card in new_cards[:DETAIL_FETCH_LIMIT]:
            try:
                detail_resp = await client.get(card["source_url"])
                detail_resp.raise_for_status()
                description, detail_category = self._extract_detail(detail_resp.text)
                candidates.append(self._to_candidate(card, section, description, detail_category))
            except Exception:
                logger.exception("Failed to fetch Workspace detail %s", card["source_url"])

        await self.state_store.set_json(
            state_key,
            {
                "recent_source_ids": merge_recent_ids(
                    recent_ids,
                    state.get("recent_source_ids", []),
                    limit=RECENT_IDS_LIMIT,
                ),
                "last_poll_at": utcnow_iso(),
            },
        )
        self.last_run_stats.add_scope(
            IngestScopeStats(
                label=section.label,
                fetched=len(cards),
                new=len(candidates),
                skipped_known=max(0, len(cards) - len(new_cards)),
            )
        )
        return candidates

    async def health_check(self) -> bool:
        try:
            sections = self._sections or []
            if not sections:
                return True
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(sections[0].url, headers={"User-Agent": USER_AGENT})
                return response.status_code == 200
        except Exception:
            return False

    @classmethod
    def _extract_cards(cls, html: str, section: WorkspaceSectionConfig) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        cards: list[dict[str, Any]] = []
        for card in soup.select("div.vacancies__card._tender[data-tender-card]"):
            link = card.select_one(".b-tender__title a[href]")
            if link is None:
                continue
            href = str(link.get("href") or "").strip()
            title = link.get_text(" ", strip=True)
            source_url = urljoin(BASE_URL, href)
            source_id = cls._extract_source_id(href)
            if not source_id or not title:
                continue

            info_items = [
                node.get_text(" ", strip=True)
                for node in card.select(".b-tender__info-item-text")
                if node.get_text(" ", strip=True)
            ]
            budget_min, budget_max = cls._extract_budget(info_items[0] if info_items else "")
            published_at = info_items[1] if len(info_items) > 1 else ""
            deadline = info_items[2] if len(info_items) > 2 else ""
            cards.append(
                {
                    "source_id": source_id,
                    "source_url": source_url,
                    "title": title,
                    "budget_min": budget_min,
                    "budget_max": budget_max,
                    "published_at": published_at,
                    "deadline": deadline,
                    "section_label": section.label,
                }
            )
        return cards

    @staticmethod
    def _extract_detail(html: str) -> tuple[str, str | None]:
        soup = BeautifulSoup(html, "lxml")
        description_node = soup.select_one(".tendercart__shot-description-top")
        description = ""
        if description_node is not None:
            description = description_node.get_text("\n", strip=True)
        category = None
        category_nodes = soup.select(".specialization-section span, .tags-list span, .specialization a")
        for node in category_nodes:
            text = node.get_text(" ", strip=True)
            if text:
                category = text
                break
        return description, category

    def _to_candidate(
        self,
        card: dict[str, Any],
        section: WorkspaceSectionConfig,
        description: str,
        detail_category: str | None,
    ) -> JobCandidateCreate:
        category = detail_category or section.category_hint or section.label
        return JobCandidateCreate(
            source=SourcePlatform.WORKSPACE,
            source_id=card["source_id"],
            source_url=card["source_url"],
            title=card["title"],
            description=description,
            budget_min=card["budget_min"],
            budget_max=card["budget_max"],
            currency="RUB",
            category=category,
            raw_data={
                "source_quality": section.source_quality,
                "source_bucket": section.source_bucket,
                "category_hint": section.category_hint,
                "feed_label": section.label,
                "matched_feeds": [section.label],
                "ingest_variant": "html_tender_list",
                "published_at": card.get("published_at"),
                "deadline": card.get("deadline"),
                "workspace_section_url": section.url,
            },
        )

    @staticmethod
    def _extract_source_id(href: str) -> str:
        match = ID_RE.search(href)
        return match.group(1) if match else href.strip("/")

    @staticmethod
    def _extract_budget(text: str) -> tuple[int | None, int | None]:
        raw_numbers = [int(part.replace(" ", "")) for part in re.findall(r"(\d[\d\s]*)", text or "")]
        if not raw_numbers:
            return None, None
        if text.strip().startswith("до"):
            return None, raw_numbers[0]
        if text.strip().startswith("от"):
            return raw_numbers[0], None
        if len(raw_numbers) >= 2:
            return raw_numbers[0], raw_numbers[1]
        return raw_numbers[0], raw_numbers[0]
