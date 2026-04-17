"""Kwork.ru collector — extracts project data from embedded stateData JSON."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from freelance_assitant.collectors.base import BaseCollector, IngestScopeStats
from freelance_assitant.collectors.registry import CollectorRegistry
from freelance_assitant.config import load_sources_config
from freelance_assitant.domain.enums import SourcePlatform
from freelance_assitant.domain.schemas import JobCandidateCreate
from freelance_assitant.storage.source_state import make_state_key, merge_recent_ids, utcnow_iso

logger = logging.getLogger("fa.collectors.kwork")

# Regex to extract stateData JSON from page HTML
STATE_DATA_PREFIX_RE = re.compile(r"window\.stateData\s*=\s*", re.DOTALL)

PROJECTS_URL = "https://kwork.ru/projects"
RECENT_IDS_LIMIT = 100
KNOWN_STREAK_STOP = 3
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@CollectorRegistry.register("kwork")
class KworkCollector(BaseCollector):
    source = SourcePlatform.KWORK

    @property
    def poll_interval_seconds(self) -> int:
        return load_sources_config().kwork.poll_seconds or self.config.kwork_poll_seconds

    async def collect(self) -> list[JobCandidateCreate]:
        self.reset_stats()
        candidates: list[JobCandidateCreate] = []
        categories = [cat for cat in load_sources_config().kwork.categories if cat.enabled]

        for category in categories:
            try:
                page_candidates = await self._collect_category(category)
                candidates.extend(page_candidates)
            except Exception:
                logger.exception(f"Failed to collect Kwork category {category.id}")

        logger.info(f"Kwork: parsed {len(candidates)} candidates")
        return candidates

    async def _collect_category(self, category) -> list[JobCandidateCreate]:
        url = f"{PROJECTS_URL}?c={category.id}"
        state_key = make_state_key(self.source.value, f"category:{category.id}")
        state = await self.state_store.get_json(state_key) or {}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "ru-RU,ru;q=0.9",
                },
            )
            resp.raise_for_status()

        state_data = self._extract_state_data(resp.text)
        if not state_data:
            logger.warning(f"No stateData found for category {category.id}")
            return []

        projects = self._extract_projects(state_data)
        known_ids = set(state.get("recent_source_ids", []))
        recent_ids = [str(proj.get("id", "")) for proj in projects if proj.get("id") is not None]
        candidates = []
        known_streak = 0
        for proj in projects:
            project_id = str(proj.get("id", ""))
            if project_id in known_ids:
                known_streak += 1
                if known_streak >= KNOWN_STREAK_STOP:
                    break
                continue

            known_streak = 0
            try:
                c = self._parse_project(proj, category)
                candidates.append(c)
            except Exception:
                logger.debug(f"Failed to parse Kwork project: {proj.get('id', '?')}")

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
        logger.info(
            "[kwork:%s] fetched=%s new=%s skipped_known=%s",
            category.id,
            len(projects),
            len(candidates),
            max(0, len(projects) - len(candidates)),
        )
        self.last_run_stats.add_scope(
            IngestScopeStats(
                label=f"{category.id}:{category.label}",
                fetched=len(projects),
                new=len(candidates),
                skipped_known=max(0, len(projects) - len(candidates)),
            )
        )
        return candidates

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.head(PROJECTS_URL, headers={"User-Agent": USER_AGENT})
                return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _extract_state_data(html: str) -> dict | None:
        match = STATE_DATA_PREFIX_RE.search(html)
        if not match:
            return None

        decoder = json.JSONDecoder()
        try:
            data, _ = decoder.raw_decode(html[match.end():].lstrip())
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_projects(state_data: dict) -> list[dict[str, Any]]:
        """Navigate stateData structure to find project listings."""
        candidates = [
            state_data.get("wantsListData"),
            state_data.get("pageData"),
            state_data,
        ]

        for candidate in candidates:
            projects = KworkCollector._find_project_list(candidate)
            if projects:
                return projects

        return []

    @classmethod
    def _find_project_list(cls, node: Any) -> list[dict[str, Any]]:
        if isinstance(node, dict):
            pagination = node.get("pagination")
            if isinstance(pagination, dict):
                data = pagination.get("data")
                if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
                    return data

            data = node.get("data")
            if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
                if any("id" in item and ("name" in item or "title" in item) for item in data):
                    return data

            for value in node.values():
                found = cls._find_project_list(value)
                if found:
                    return found

        if isinstance(node, list):
            for item in node:
                found = cls._find_project_list(item)
                if found:
                    return found

        return []

    def _parse_project(self, proj: dict, category) -> JobCandidateCreate:
        project_id = str(proj.get("id", ""))
        name = proj.get("name", "") or proj.get("title", "")
        description = proj.get("description", "") or ""
        price_limit = (
            proj.get("priceLimit")
            or proj.get("price_limit")
            or proj.get("price")
            or proj.get("budget")
        )

        # Build source URL
        source_url = f"https://kwork.ru/projects/{project_id}"

        # Extract budget
        budget = None
        if price_limit:
            try:
                budget = int(str(price_limit).replace(" ", ""))
            except (ValueError, TypeError):
                pass

        # Client info
        user = proj.get("user", {}) or {}
        client_name = user.get("username") or user.get("name")

        return JobCandidateCreate(
            source=SourcePlatform.KWORK,
            source_id=project_id,
            source_url=source_url,
            title=name,
            description=description,
            budget_min=budget,
            budget_max=budget,
            currency="RUB",
            client_name=client_name,
            category=category.label,
            raw_data={
                **proj,
                "source_quality": category.source_quality,
                "source_bucket": category.source_bucket,
                "category_hint": category.label,
                "category_id": category.id,
                "category_label": category.label,
                "matched_feeds": [],
                "ingest_variant": "embedded_state",
            },
        )
