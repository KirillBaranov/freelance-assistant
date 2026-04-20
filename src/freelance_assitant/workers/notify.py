"""Notification worker — sends A-lead notifications to each user."""

from __future__ import annotations

import logging

from freelance_assitant.bot.notify import send_lead_notification
from freelance_assitant.bot.setup import get_bot
from freelance_assitant.config import load_users, settings
from freelance_assitant.storage.repo import JobCandidateRepo

logger = logging.getLogger("fa.workers.notify")


async def notify_leads(ctx: dict) -> int:
    """arq task: send Telegram notifications for each user's shortlisted leads."""
    if not settings.telegram_bot_token:
        return 0

    session_factory = ctx["session_factory"]
    bot = get_bot()
    users = load_users()
    sent = 0

    if users:
        for user in users:
            user_id = str(user.telegram_id)
            async with session_factory() as session:
                repo = JobCandidateRepo(session)
                leads = await repo.get_user_shortlisted_unnotified(user_id, limit=10)

            for lead in leads:
                msg_id = await send_lead_notification(bot, user.telegram_id, lead)
                if msg_id:
                    async with session_factory() as session:
                        repo = JobCandidateRepo(session)
                        await repo.mark_user_notified(user_id, lead.id)
                    sent += 1
                    logger.info(
                        f"[{user.name}] Notified: {lead.id} ({lead.title[:50]})"
                    )
    else:
        # Fallback: legacy single-user
        if not settings.telegram_owner_id:
            return 0
        async with session_factory() as session:
            repo = JobCandidateRepo(session)
            leads = await repo.get_shortlisted_unnotified(limit=10)
        for lead in leads:
            msg_id = await send_lead_notification(bot, settings.telegram_owner_id, lead)
            if msg_id:
                async with session_factory() as session:
                    repo = JobCandidateRepo(session)
                    await repo.mark_notified(lead.id)
                sent += 1

    if sent > 0:
        logger.info(f"Sent {sent} Telegram notifications total")
    return sent
