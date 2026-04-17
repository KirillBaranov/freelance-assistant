"""Bot commands."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from freelance_assitant.bot.keyboard import leads_nav_keyboard, pipeline_lead_keyboard
from freelance_assitant.bot.notify import format_lead_message
from freelance_assitant.config import settings
from freelance_assitant.domain.enums import JobStatus
from freelance_assitant.storage.database import async_session_factory
from freelance_assitant.storage.models import JobCandidate
from freelance_assitant.storage.repo import JobCandidateRepo

logger = logging.getLogger("fa.bot.commands")
router = Router(name="commands")

ACTIVE_STATUSES = [
    JobStatus.SHORTLISTED,
    JobStatus.DRAFT_READY,
    JobStatus.APPROVED,
    JobStatus.APPLIED,
    JobStatus.CLIENT_REPLIED,
    JobStatus.FOLLOWUP_DUE,
]

STATUS_EMOJI = {
    JobStatus.SHORTLISTED: "🔵",
    JobStatus.DRAFT_READY: "✍",
    JobStatus.APPROVED: "✅",
    JobStatus.APPLIED: "📤",
    JobStatus.CLIENT_REPLIED: "✉️",
    JobStatus.FOLLOWUP_DUE: "⏰",
}


def _owner_only(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == settings.telegram_owner_id)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    if not _owner_only(message):
        await message.answer("Access denied.")
        return
    await message.answer(
        "👋 <b>Freelance Assistant</b>\n\n"
        "Команды:\n"
        "/leads — просмотр лидов по одному\n"
        "/pipeline — активный pipeline\n"
        "/stats — статистика за сегодня\n"
        "/today — выручка за день",
        parse_mode="HTML",
    )


PAGE_SIZE = 5


async def _send_leads_page(target: Message, offset: int) -> None:
    async with async_session_factory() as session:
        repo = JobCandidateRepo(session)
        total = await repo.count_by_status(JobStatus.SHORTLISTED)
        leads = await repo.get_by_status(JobStatus.SHORTLISTED, limit=PAGE_SIZE, offset=offset)

    if not leads:
        await target.answer("Нет лидов в shortlist.")
        return

    for lead in leads:
        text = format_lead_message(lead)
        kb = pipeline_lead_keyboard(str(lead.id), lead.source_url)
        await target.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)

    nav = leads_nav_keyboard(offset, total, PAGE_SIZE)
    summary = f"Показано {offset + 1}–{min(offset + PAGE_SIZE, total)} из {total}"
    await target.answer(summary, reply_markup=nav)


@router.message(Command("leads"), _owner_only)
async def cmd_leads(message: Message) -> None:
    await _send_leads_page(message, offset=0)


@router.callback_query(lambda c: c.data and c.data.startswith("leads_page:"))
async def handle_leads_page(callback: CallbackQuery) -> None:
    await callback.answer()
    try:
        offset = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    await _send_leads_page(callback.message, offset=offset)


@router.callback_query(lambda c: c.data == "noop")
async def handle_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(Command("pipeline"), _owner_only)
async def cmd_pipeline(message: Message) -> None:
    """Show active pipeline grouped by status."""
    async with async_session_factory() as session:
        stmt = (
            select(JobCandidate)
            .where(JobCandidate.status.in_(ACTIVE_STATUSES))
            .order_by(JobCandidate.updated_at.desc())
            .limit(30)
        )
        result = await session.execute(stmt)
        candidates = result.scalars().all()

    if not candidates:
        await message.answer("Pipeline пуст.")
        return

    by_status: dict[str, list] = {}
    for c in candidates:
        by_status.setdefault(c.status, []).append(c)

    lines = ["📋 <b>Pipeline</b>\n"]
    for status in ACTIVE_STATUSES:
        items = by_status.get(status, [])
        if not items:
            continue
        emoji = STATUS_EMOJI.get(status, "•")
        lines.append(f"{emoji} <b>{status}</b> ({len(items)})")
        for c in items[:5]:
            budget = ""
            if c.budget_max or c.budget_min:
                b = c.budget_max or c.budget_min
                budget = f" · {b:,} ₽"
            score = f" · {c.score:.2f}" if c.score else ""
            lines.append(f"  — {c.title[:45]}{budget}{score}")
        if len(items) > 5:
            lines.append(f"  … ещё {len(items) - 5}")
        lines.append("")

    # Summary buttons for shortlisted
    shortlisted = by_status.get(JobStatus.SHORTLISTED, [])
    kb = None
    if shortlisted:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"👀 Разобрать {len(shortlisted)} лидов", callback_data="open_leads"),
        ]])

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)


@router.message(Command("stats"), _owner_only)
async def cmd_stats(message: Message) -> None:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    async with async_session_factory() as session:
        total_today = await _count(session, JobCandidate.created_at >= today_start)
        a_today = await _count(session, JobCandidate.created_at >= today_start, JobCandidate.tier == "A")
        b_today = await _count(session, JobCandidate.created_at >= today_start, JobCandidate.tier == "B")
        applied = await _count(session, JobCandidate.status == JobStatus.APPLIED)
        won_today = await _count(
            session, JobCandidate.status == JobStatus.WON, JobCandidate.updated_at >= today_start
        )
        total_week = await _count(session, JobCandidate.created_at >= week_start)
        shortlisted = await _count(session, JobCandidate.status == JobStatus.SHORTLISTED)

    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"<b>Сегодня</b>\n"
        f"📥 Новых лидов: {total_today} (A: {a_today}, B: {b_today})\n"
        f"🔵 Shortlist: {shortlisted}\n"
        f"📤 Откликов: {applied}\n"
        f"🏆 Выиграно: {won_today}\n\n"
        f"<b>За 7 дней</b>\n"
        f"📦 Всего лидов: {total_week}",
        parse_mode="HTML",
    )


@router.message(Command("today"), _owner_only)
async def cmd_today(message: Message) -> None:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session_factory() as session:
        stmt = select(JobCandidate).where(
            JobCandidate.status == JobStatus.WON,
            JobCandidate.updated_at >= today_start,
        )
        result = await session.execute(stmt)
        won = result.scalars().all()

    total = sum((c.budget_max or c.budget_min or 0) for c in won)
    target = 5000
    progress = min(total / target, 1.0) if target else 0
    filled = int(progress * 10)
    bar = "█" * filled + "░" * (10 - filled)

    if won:
        lines = [f"💰 <b>Сегодня: {total:,} ₽ / {target:,} ₽</b>\n"]
        for c in won:
            budget = c.budget_max or c.budget_min or 0
            lines.append(f"• {c.title[:50]} — {budget:,} ₽")
    else:
        lines = [f"💰 <b>Сегодня: 0 / {target:,} ₽</b>\n\nПока пусто. Время действовать!"]

    lines.append(f"\n[{bar}] {progress:.0%}")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def _count(session, *filters) -> int:
    stmt = select(func.count()).select_from(JobCandidate).where(*filters)
    result = await session.execute(stmt)
    return result.scalar() or 0
