"""Workspace.ru tender status checker."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup

from freelance_assitant.status_checkers.base import BaseStatusChecker, CheckResult, CloseReason
from freelance_assitant.status_checkers.registry import StatusCheckerRegistry

if TYPE_CHECKING:
    from freelance_assitant.storage.models import JobCandidate

logger = logging.getLogger("fa.status_checkers.workspace")

CLOSED_MARKERS = [
    "Исполнитель выбран",
    "Тендер закрыт",
    "Завершён",
    "Завершен",
    "Архив",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


@StatusCheckerRegistry.register("workspace")
class WorkspaceStatusChecker(BaseStatusChecker):
    source = "workspace"

    def __init__(self, config: dict | None = None):
        self._cfg = config or {}
        self._closed_markers: list[str] = self._cfg.get("closed_markers", CLOSED_MARKERS)

    async def check(self, candidate: JobCandidate) -> CheckResult:
        url = candidate.source_url
        if not url:
            return CheckResult(should_close=False)

        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers=HEADERS)

            if resp.status_code == 404:
                return CheckResult(should_close=True, reason=CloseReason.NOT_FOUND, raw="HTTP 404")

            if resp.status_code != 200:
                return CheckResult(should_close=False)

            # Check plain text first (fast)
            html = resp.text
            for marker in self._closed_markers:
                if marker.lower() in html.lower():
                    logger.info("[workspace] marker '%s' → close: %s", marker, url)
                    return CheckResult(should_close=True, reason=CloseReason.CLOSED, raw=marker)

            # Check status badge via BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            status_el = soup.select_one(".tender-status, .status-badge, [class*='status']")
            if status_el:
                status_text = status_el.get_text(strip=True)
                for marker in self._closed_markers:
                    if marker.lower() in status_text.lower():
                        return CheckResult(should_close=True, reason=CloseReason.CLOSED, raw=status_text)

            return CheckResult(should_close=False)

        except Exception as e:
            logger.warning("[workspace] check failed for %s: %s", url, e)
            return CheckResult(should_close=False)
