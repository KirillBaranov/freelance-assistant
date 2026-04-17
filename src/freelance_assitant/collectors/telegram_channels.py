"""Telegram channel collector — monitors configured channels via Telethon userbot."""

from __future__ import annotations

import asyncio
import logging
import re
from hashlib import md5
from typing import Any

from freelance_assitant.config import load_sources_config, settings
from freelance_assitant.domain.enums import SourcePlatform
from freelance_assitant.domain.schemas import JobCandidateCreate

logger = logging.getLogger("fa.collectors.telegram")

# Keywords that signal a job posting
DEFAULT_KEYWORDS = [
    "python", "бот", "парсинг", "парсер", "скрипт", "автоматизация",
    "api", "backend", "бэкенд", "fastapi", "django", "telegram",
    "интеграция", "разработк", "программист", "разработчик",
]

# Budget patterns in free-text messages
BUDGET_RE = re.compile(
    r"(?:бюджет|оплата|ставка|цена|стоимость)[:\s]*(\d[\d\s]*)\s*(?:руб|₽|р\b|rub)",
    re.IGNORECASE,
)


async def start_channel_monitor(on_new_job) -> None:
    """Start Telethon userbot to monitor configured Telegram channels.

    Args:
        on_new_job: async callback(JobCandidateCreate) called for each detected job posting.
    """
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        logger.warning("Telethon credentials not configured, channel monitoring disabled")
        while True:
            await asyncio.sleep(3600)
        return

    configured_channels = _configured_channels()
    if not configured_channels:
        logger.warning("No Telegram channels configured for monitoring")
        while True:
            await asyncio.sleep(3600)
        return

    try:
        from telethon import TelegramClient, events
    except ImportError:
        logger.error("Telethon not installed. Run: pip install telethon")
        return

    client = TelegramClient(
        "fa_userbot",
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    @client.on(events.NewMessage(chats=[channel["handle"] for channel in configured_channels]))
    async def handler(event):
        text = event.message.text or ""
        if not _is_job_posting(text):
            return

        try:
            candidate = _parse_message(event, configured_channels)
            await on_new_job(candidate)
            logger.info(f"New job from Telegram: {candidate.title[:50]}")
        except Exception:
            logger.exception("Failed to parse Telegram message as job")

    await client.start()
    logger.info(f"Monitoring {len(configured_channels)} Telegram channels")
    await client.run_until_disconnected()


def _is_job_posting(text: str) -> bool:
    """Check if a message looks like a job posting."""
    if len(text) < 50:
        return False

    text_lower = text.lower()
    hits = sum(1 for kw in DEFAULT_KEYWORDS if kw in text_lower)
    return hits >= 2


def _configured_channels() -> list[dict[str, Any]]:
    file_channels = [
        {
            "handle": channel.handle,
            "label": channel.label or channel.handle,
            "quality": channel.quality,
            "tags": channel.tags,
        }
        for channel in load_sources_config().telegram.channels
        if channel.enabled
    ]
    if file_channels:
        return file_channels

    return [
        {"handle": handle, "label": handle, "quality": "medium", "tags": []}
        for handle in settings.telegram_channels
    ]


def _parse_message(event, configured_channels: list[dict[str, Any]]) -> JobCandidateCreate:
    """Parse a Telegram message into a JobCandidateCreate."""
    text = event.message.text or ""
    chat = event.chat

    # Title = first line or first 80 chars
    first_line = text.split("\n")[0][:80]
    title = first_line if len(first_line) > 10 else text[:80]

    # Generate stable source_id from message content hash
    source_id = md5(f"{chat.id}:{event.message.id}".encode()).hexdigest()[:16]

    # Source URL
    chat_username = getattr(chat, "username", None)
    if chat_username:
        source_url = f"https://t.me/{chat_username}/{event.message.id}"
    else:
        source_url = f"https://t.me/c/{chat.id}/{event.message.id}"

    # Extract budget
    budget = _extract_budget(text)
    chat_username = getattr(chat, "username", None)
    channel_meta = next(
        (
            channel
            for channel in configured_channels
            if channel["handle"].lstrip("@") == (chat_username or "").lstrip("@")
        ),
        None,
    )

    return JobCandidateCreate(
        source=SourcePlatform.TELEGRAM,
        source_id=source_id,
        source_url=source_url,
        title=title.strip(),
        description=text,
        budget_min=budget,
        budget_max=budget,
        currency="RUB",
        client_name=chat_username or str(chat.id),
        category="Telegram",
        raw_data={
            "chat_id": chat.id,
            "message_id": event.message.id,
            "chat_title": getattr(chat, "title", ""),
            "source_quality": (channel_meta or {}).get("quality", "medium"),
            "source_bucket": "telegram_channel",
            "category_hint": "Telegram",
            "matched_channel": (channel_meta or {}).get("label", chat_username or str(chat.id)),
            "channel_tags": (channel_meta or {}).get("tags", []),
            "ingest_variant": "telethon_channel",
        },
    )


def _extract_budget(text: str) -> int | None:
    match = BUDGET_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace("\xa0", "")
    try:
        return int(raw)
    except ValueError:
        return None
