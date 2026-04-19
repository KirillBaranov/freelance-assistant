"""Follow-up worker — sends reminders for stale applications."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from freelance_assitant.bot.setup import get_bot
from freelance_assitant.bot.keyboard import status_keyboard
from aiogram.utils.markdown import html_decoration as hd
from freelance_assitant.config import settings
from freelance_assitant.domain.enums import JobStatus
from freelance_assitant.storage.models import JobCandidate

logger = logging.getLogger("fa.workers.followup")


async def followup_check(ctx: dict) -> int:
    """arq cron task: check for stale applications and send reminders."""
    if not settings.telegram_bot_token or not settings.telegram_owner_id:
        return 0

    session_factory = ctx["session_factory"]
    bot = get_bot()
    reminded = 0
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        # Find candidates stuck in "applied" for > 48 hours
        cutoff = now - timedelta(hours=48)
        stmt = (
            select(JobCandidate)
            .where(
                JobCandidate.status == JobStatus.APPLIED,
                JobCandidate.updated_at < cutoff,
            )
            .limit(10)
        )
        result = await session.execute(stmt)
        stale = result.scalars().all()

        for candidate in stale:
            try:
                hours_ago = int((now - candidate.updated_at).total_seconds() / 3600)
                text = (
                    f"\u23f0 <b>Напоминание</b>\n\n"
                    f"📋 {hd.quote(candidate.title[:80])}\n"
                    f"\ud83d\udd52 Отклик отправлен {hours_ago}ч назад\n"
                    f"\nКлиент ответил?"
                )
                await bot.send_message(
                    chat_id=settings.telegram_owner_id,
                    text=text,
                    reply_markup=status_keyboard(str(candidate.id)),
                    parse_mode="HTML",
                )
                # Move to followup_due so we don't re-remind next cycle
                candidate.status = JobStatus.FOLLOWUP_DUE
                reminded += 1
            except Exception:
                logger.exception(f"Failed to send followup for {candidate.id}")

        if stale:
            await session.commit()

    if reminded:
        logger.info(f"Sent {reminded} follow-up reminders")
    return reminded
