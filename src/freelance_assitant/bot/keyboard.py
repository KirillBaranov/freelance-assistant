"""Inline keyboard builders for Telegram bot."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def lead_keyboard(candidate_id: str, source_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✍ Отклик", callback_data=f"draft:{candidate_id}"),
            InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip:{candidate_id}"),
        ],
        [
            InlineKeyboardButton(text="🕐 Позже", callback_data=f"later:{candidate_id}"),
            InlineKeyboardButton(text="🔗 Открыть", url=source_url),
        ],
    ])


def proposal_keyboard(candidate_id: str, source_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data=f"approve:{candidate_id}"),
            InlineKeyboardButton(text="🔄 Заново", callback_data=f"regen:{candidate_id}"),
        ],
        [
            InlineKeyboardButton(text="🔗 Открыть", url=source_url),
        ],
    ])


def status_keyboard(candidate_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✉️ Ответили", callback_data=f"replied:{candidate_id}"),
            InlineKeyboardButton(text="🏆 Выиграл", callback_data=f"won:{candidate_id}"),
        ],
        [
            InlineKeyboardButton(text="❌ Проиграл", callback_data=f"lost:{candidate_id}"),
        ],
    ])


def pipeline_lead_keyboard(candidate_id: str, source_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✍ Отклик", callback_data=f"draft:{candidate_id}"),
            InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"skip:{candidate_id}"),
            InlineKeyboardButton(text="🔗", url=source_url),
        ],
    ])


def leads_nav_keyboard(offset: int, total: int, page_size: int = 5) -> InlineKeyboardMarkup | None:
    """Navigation keyboard for /leads pagination."""
    has_next = offset + page_size < total
    has_prev = offset > 0
    if not has_next and not has_prev:
        return None
    buttons = []
    if has_prev:
        buttons.append(InlineKeyboardButton(text="← Назад", callback_data=f"leads_page:{offset - page_size}"))
    buttons.append(InlineKeyboardButton(text=f"{offset // page_size + 1}/{(total + page_size - 1) // page_size}", callback_data="noop"))
    if has_next:
        buttons.append(InlineKeyboardButton(text="Далее →", callback_data=f"leads_page:{offset + page_size}"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
