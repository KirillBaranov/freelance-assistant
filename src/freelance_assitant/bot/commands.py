"""Bot commands — /stats, /pipeline, /today."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select

from freelance_assitant.config import settings
from freelance_assitant.domain.enums import JobStatus
from freelance_assitant.storage.database import async_session_factory
from freelance_assitant.storage.models import JobCandidate

logger = logging.getLogger("fa.bot.commands")
router = Router(name="commands")


def _owner_only(message: Message) -> bool:
    return message.from_user and message.from_user.id == settings.telegram_owner_id


@router.message(Command("stats"), _owner_only)
async def cmd_stats(message: Message) -> None:
    """Show daily summary."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_factory() as session:
        # Total today
        total = await _count(session, JobCandidate.created_at >= today_start)
        # By tier
        a_count = await _count(session, JobCandidate.created_at >= today_start, JobCandidate.tier == "A")
        b_count = await _count(session, JobCandidate.created_at >= today_start, JobCandidate.tier == "B")
        # Applied
        applied = await _count(session, JobCandidate.status == JobStatus.APPLIED)
        # Won
        won_today = await _count(
            session,
            JobCandidate.status == JobStatus.WON,
            JobCandidate.updated_at >= today_start,
        )

    text = (
        f"\ud83d\udcca <b>Статистика за сегодня</b>\n\n"
        f"\ud83d\udce5 Новых лидов: {total}\n"
        f"\ud83c\udd70\ufe0f A-лидов: {a_count}\n"
        f"\ud83c\udd71\ufe0f B-лидов: {b_count}\n"
        f"\ud83d\udce4 Откликов отправлено: {applied}\n"
        f"\ud83c\udfc6 Выиграно: {won_today}"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("pipeline"), _owner_only)
async def cmd_pipeline(message: Message) -> None:
    """Show active pipeline."""
    async with async_session_factory() as session:
        active_statuses = [
            JobStatus.SHORTLISTED,
            JobStatus.DRAFT_READY,
            JobStatus.APPROVED,
            JobStatus.APPLIED,
            JobStatus.CLIENT_REPLIED,
            JobStatus.FOLLOWUP_DUE,
        ]
        stmt = (
            select(JobCandidate)
            .where(JobCandidate.status.in_(active_statuses))
            .order_by(JobCandidate.updated_at.desc())
            .limit(20)
        )
        result = await session.execute(stmt)
        candidates = result.scalars().all()

    if not candidates:
        await message.answer("Pipeline пуст")
        return

    lines = ["\ud83d\udccb <b>Активный pipeline</b>\n"]
    for c in candidates:
        status_emoji = {
            JobStatus.SHORTLISTED: "\ud83d\udd35",
            JobStatus.DRAFT_READY: "\u270d",
            JobStatus.APPROVED: "\u2705",
            JobStatus.APPLIED: "\ud83d\udce4",
            JobStatus.CLIENT_REPLIED: "\u2709\ufe0f",
            JobStatus.FOLLOWUP_DUE: "\u23f0",
        }.get(c.status, "\u2022")
        title_short = c.title[:50]
        lines.append(f"{status_emoji} <b>{c.status}</b>: {title_short}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("today"), _owner_only)
async def cmd_today(message: Message) -> None:
    """Show today's earnings tracking."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_factory() as session:
        stmt = (
            select(JobCandidate)
            .where(
                JobCandidate.status == JobStatus.WON,
                JobCandidate.updated_at >= today_start,
            )
        )
        result = await session.execute(stmt)
        won = result.scalars().all()

    total = sum((c.budget_max or c.budget_min or 0) for c in won)
    target = 5000

    if won:
        lines = [f"\ud83d\udcb0 <b>Сегодня: {total:,} \u20bd / {target:,} \u20bd</b>\n"]
        for c in won:
            budget = c.budget_max or c.budget_min or 0
            lines.append(f"\u2022 {c.title[:50]} — {budget:,} \u20bd")
    else:
        lines = [f"\ud83d\udcb0 <b>Сегодня: 0 / {target:,} \u20bd</b>\n\nПока пусто. Время действовать!"]

    progress = min(total / target, 1.0) if target else 0
    bar_len = 10
    filled = int(progress * bar_len)
    bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
    lines.append(f"\n[{bar}] {progress:.0%}")

    await message.answer("\n".join(lines), parse_mode="HTML")


async def _count(session, *filters) -> int:
    stmt = select(func.count()).select_from(JobCandidate).where(*filters)
    result = await session.execute(stmt)
    return result.scalar() or 0
