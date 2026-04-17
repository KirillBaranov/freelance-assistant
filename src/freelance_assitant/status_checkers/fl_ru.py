"""FL.ru job status checker.

Fetches the job page and looks for markers indicating the job is closed.
Configurable via config/status_check.yaml → platforms.fl_ru.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from freelance_assitant.status_checkers.base import BaseStatusChecker, CheckResult, CloseReason
from freelance_assitant.status_checkers.registry import StatusCheckerRegistry

if TYPE_CHECKING:
    from freelance_assitant.storage.models import JobCandidate

logger = logging.getLogger("fa.status_checkers.fl_ru")

# Markers on FL.ru page that mean the job is no longer accepting proposals
CLOSED_MARKERS = [
    "Исполнитель выбран",
    "Заказ закрыт",
    "Работа закрыта",
    "Работа удалена",
    "Проект закрыт",
    "Закрытый проект",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}


@StatusCheckerRegistry.register("fl_ru")
class FlRuStatusChecker(BaseStatusChecker):
    source = "fl_ru"

    def __init__(self, config: dict | None = None):
        self._cfg = config or {}
        self._closed_markers: list[str] = self._cfg.get("closed_markers", CLOSED_MARKERS)
        self._http_404_closes: bool = self._cfg.get("http_404_closes", True)

    async def check(self, candidate: JobCandidate) -> CheckResult:
        url = candidate.source_url
        if not url:
            return CheckResult(should_close=False)

        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers=HEADERS)

            if resp.status_code == 404:
                logger.info("[fl_ru] 404 → close: %s", url)
                return CheckResult(should_close=True, reason=CloseReason.NOT_FOUND, raw="HTTP 404")

            if resp.status_code != 200:
                return CheckResult(should_close=False)

            html = resp.text
            for marker in self._closed_markers:
                if marker.lower() in html.lower():
                    logger.info("[fl_ru] marker '%s' → close: %s", marker, url)
                    return CheckResult(should_close=True, reason=CloseReason.EXECUTOR_SELECTED, raw=marker)

            return CheckResult(should_close=False)

        except Exception as e:
            logger.warning("[fl_ru] check failed for %s: %s", url, e)
            return CheckResult(should_close=False)
