"""Proposal generation worker."""

from __future__ import annotations

import logging
import uuid

from freelance_assitant.bot.keyboard import proposal_keyboard
from freelance_assitant.bot.notify import _escape_html
from freelance_assitant.bot.setup import get_bot
from freelance_assitant.config import settings
from freelance_assitant.proposal.generator import generate_proposal
from freelance_assitant.storage.repo import JobCandidateRepo

logger = logging.getLogger("fa.workers.proposal")


async def generate_proposal_task(ctx: dict, candidate_id: str) -> bool:
    """arq task: generate a proposal draft and send to Telegram."""
    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        repo = JobCandidateRepo(session)
        candidate = await repo.get_by_id(uuid.UUID(candidate_id))
        if not candidate:
            logger.error(f"Candidate {candidate_id} not found")
            return False

        try:
            draft = await generate_proposal(candidate)
            await repo.update_proposal(candidate.id, draft)
        except Exception:
            logger.exception(f"Proposal generation failed for {candidate_id}")
            return False

    # Send draft to Telegram
    if settings.telegram_bot_token and settings.telegram_owner_id:
        try:
            bot = get_bot()
            text = (
                f"\u270d <b>Отклик для:</b> {_escape_html(candidate.title[:80])}\n"
                f"\n{_escape_html(draft)}"
            )
            kb = proposal_keyboard(str(candidate.id), candidate.source_url)
            await bot.send_message(
                chat_id=settings.telegram_owner_id,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Failed to send proposal to Telegram")

    logger.info(f"Proposal generated for {candidate_id}")
    return True
