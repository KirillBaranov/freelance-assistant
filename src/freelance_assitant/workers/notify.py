"""Notification worker — sends A-lead notifications to Telegram."""

from __future__ import annotations

import logging

from freelance_assitant.bot.notify import send_lead_notification
from freelance_assitant.bot.setup import get_bot
from freelance_assitant.config import settings
from freelance_assitant.storage.repo import JobCandidateRepo

logger = logging.getLogger("fa.workers.notify")


async def notify_leads(ctx: dict) -> int:
    """arq task: send Telegram notifications for shortlisted, unnotified leads."""
    if not settings.telegram_bot_token or not settings.telegram_owner_id:
        return 0

    session_factory = ctx["session_factory"]
    bot = get_bot()
    sent = 0

    async with session_factory() as session:
        repo = JobCandidateRepo(session)
        leads = await repo.get_shortlisted_unnotified(limit=10)

        for lead in leads:
            msg_id = await send_lead_notification(bot, settings.telegram_owner_id, lead)
            if msg_id:
                await repo.mark_notified(lead.id)
                sent += 1

    if sent > 0:
        logger.info(f"Sent {sent} Telegram notifications")
    return sent
