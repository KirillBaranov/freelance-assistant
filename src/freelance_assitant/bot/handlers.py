"""Callback handlers for inline keyboard actions."""

from __future__ import annotations

import logging
import uuid

from aiogram import Bot, Router
from aiogram.types import CallbackQuery

from freelance_assitant.bot.keyboard import pipeline_lead_keyboard, proposal_keyboard, status_keyboard
from freelance_assitant.bot.notify import format_lead_message
from freelance_assitant.config import settings
from freelance_assitant.domain.enums import JobStatus
from freelance_assitant.storage.database import async_session_factory
from freelance_assitant.storage.redis import get_redis_settings
from freelance_assitant.storage.repo import JobCandidateRepo

logger = logging.getLogger("fa.bot.handlers")
router = Router(name="lead_actions")


@router.callback_query(lambda c: c.data and c.data.startswith("draft:"))
async def handle_draft(callback: CallbackQuery, bot: Bot) -> None:
    """Generate proposal draft for this lead."""
    candidate_id = _extract_id(callback.data)
    if not candidate_id:
        await callback.answer("Invalid candidate")
        return

    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        await repo.update_status(candidate_id, JobStatus.DRAFT_READY)

    await callback.answer("Готовлю отклик...")
    await callback.message.edit_reply_markup(reply_markup=None)

    # Enqueue proposal generation via arq
    try:
        from arq.connections import create_pool
        pool = await create_pool(get_redis_settings())
        await pool.enqueue_job("generate_proposal_task", str(candidate_id))
        await pool.aclose()
    except Exception:
        logger.exception("Failed to enqueue proposal generation")

    logger.info(f"Draft requested for {candidate_id}")


@router.callback_query(lambda c: c.data and c.data.startswith("skip:"))
async def handle_skip(callback: CallbackQuery) -> None:
    """Skip/archive this lead."""
    candidate_id = _extract_id(callback.data)
    if not candidate_id:
        await callback.answer("Invalid candidate")
        return

    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        await repo.update_status(candidate_id, JobStatus.ARCHIVED)

    await callback.answer("Пропущено")
    # Strike through the message
    if callback.message and callback.message.text:
        await callback.message.edit_text(
            f"<s>{callback.message.text}</s>\n\n\u274c Пропущено",
            parse_mode="HTML",
        )
    logger.info(f"Skipped {candidate_id}")


@router.callback_query(lambda c: c.data and c.data.startswith("later:"))
async def handle_later(callback: CallbackQuery) -> None:
    """Snooze — revisit later."""
    candidate_id = _extract_id(callback.data)
    if not candidate_id:
        await callback.answer("Invalid candidate")
        return

    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        await repo.update_status(candidate_id, JobStatus.FOLLOWUP_DUE)

    await callback.answer("Напомню позже")
    logger.info(f"Snoozed {candidate_id}")


@router.callback_query(lambda c: c.data and c.data.startswith("approve:"))
async def handle_approve(callback: CallbackQuery) -> None:
    """Approve proposal — mark as approved, user sends manually."""
    candidate_id = _extract_id(callback.data)
    if not candidate_id:
        await callback.answer("Invalid candidate")
        return

    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        candidate = await repo.get_by_id(candidate_id)
        await repo.update_status(candidate_id, JobStatus.APPROVED)

    await callback.answer("Отклик одобрен! Отправь вручную на бирже.")
    if callback.message and candidate:
        await callback.message.edit_reply_markup(
            reply_markup=status_keyboard(str(candidate_id))
        )
    logger.info(f"Approved {candidate_id}")


@router.callback_query(lambda c: c.data and c.data.startswith("regen:"))
async def handle_regen(callback: CallbackQuery) -> None:
    """Regenerate proposal draft."""
    candidate_id = _extract_id(callback.data)
    if not candidate_id:
        await callback.answer("Invalid candidate")
        return

    await callback.answer("Генерирую заново...")
    # Will trigger proposal re-generation in Phase 4
    logger.info(f"Regen requested for {candidate_id}")


@router.callback_query(lambda c: c.data and c.data.startswith("replied:"))
async def handle_replied(callback: CallbackQuery) -> None:
    candidate_id = _extract_id(callback.data)
    if not candidate_id:
        return

    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        await repo.update_status(candidate_id, JobStatus.CLIENT_REPLIED)

    await callback.answer("Отмечено: клиент ответил")


@router.callback_query(lambda c: c.data and c.data.startswith("won:"))
async def handle_won(callback: CallbackQuery) -> None:
    candidate_id = _extract_id(callback.data)
    if not candidate_id:
        return

    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        await repo.update_status(candidate_id, JobStatus.WON)

    await callback.answer("🏆 Победа!")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(lambda c: c.data and c.data.startswith("lost:"))
async def handle_lost(callback: CallbackQuery) -> None:
    candidate_id = _extract_id(callback.data)
    if not candidate_id:
        return

    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        await repo.update_status(candidate_id, JobStatus.LOST)

    await callback.answer("Отмечено: проиграл")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(lambda c: c.data == "open_leads")
async def handle_open_leads(callback: CallbackQuery) -> None:
    await callback.answer()
    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        leads = await repo.get_by_status(JobStatus.SHORTLISTED, limit=5)

    if not leads:
        await callback.message.answer("Нет лидов в shortlist.")
        return

    for lead in leads:
        text = format_lead_message(lead)
        kb = pipeline_lead_keyboard(str(lead.id), lead.source_url)
        await callback.message.answer(
            text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


def _extract_id(data: str | None) -> uuid.UUID | None:
    if not data:
        return None
    try:
        _, raw_id = data.split(":", 1)
        return uuid.UUID(raw_id)
    except (ValueError, AttributeError):
        return None
