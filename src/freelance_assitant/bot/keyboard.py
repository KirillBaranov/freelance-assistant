"""Inline keyboard builders for Telegram bot."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def lead_keyboard(candidate_id: str, source_url: str) -> InlineKeyboardMarkup:
    """Keyboard for a new A-lead notification."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="\u270d Написать", callback_data=f"draft:{candidate_id}"
            ),
            InlineKeyboardButton(
                text="\u23ed Пропустить", callback_data=f"skip:{candidate_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="\ud83d\udd50 Позже", callback_data=f"later:{candidate_id}"
            ),
            InlineKeyboardButton(
                text="\ud83d\udd17 Открыть", url=source_url
            ),
        ],
    ])


def proposal_keyboard(candidate_id: str, source_url: str) -> InlineKeyboardMarkup:
    """Keyboard for a generated proposal draft."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="\u2705 Отправить", callback_data=f"approve:{candidate_id}"
            ),
            InlineKeyboardButton(
                text="\ud83d\udd04 Заново", callback_data=f"regen:{candidate_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="\ud83d\udd17 Открыть", url=source_url
            ),
        ],
    ])


def status_keyboard(candidate_id: str) -> InlineKeyboardMarkup:
    """Keyboard for status updates after applying."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="\u2709\ufe0f Ответили", callback_data=f"replied:{candidate_id}"
            ),
            InlineKeyboardButton(
                text="\ud83c\udfc6 Выиграл", callback_data=f"won:{candidate_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="\u274c Проиграл", callback_data=f"lost:{candidate_id}"
            ),
        ],
    ])
