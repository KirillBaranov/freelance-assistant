"""Telegram bot setup — aiogram 3.x dispatcher."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from freelance_assitant.bot.commands import router as commands_router
from freelance_assitant.bot.handlers import router
from freelance_assitant.config import settings

logger = logging.getLogger("fa.bot")

_bot: Bot | None = None


def get_bot() -> Bot:
    """Get or create the bot singleton."""
    global _bot
    if _bot is None:
        if not settings.telegram_bot_token:
            raise RuntimeError("FA_TELEGRAM_BOT_TOKEN is not set")
        _bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode="HTML"),
        )
    return _bot


async def start_bot() -> None:
    """Start the Telegram bot polling."""
    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not configured, skipping bot startup")
        import asyncio
        while True:
            await asyncio.sleep(3600)
        return

    bot = get_bot()
    dp = Dispatcher()
    dp.include_router(router)
    dp.include_router(commands_router)

    logger.info("Starting Telegram bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=["callback_query", "message"])
    finally:
        await bot.session.close()
