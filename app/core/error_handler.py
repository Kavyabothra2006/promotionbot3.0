from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import ErrorEvent

from app.config import settings

logger = logging.getLogger(__name__)


async def on_error(event: ErrorEvent, bot: Bot) -> bool:
    exc = event.exception
    logger.exception("Unhandled Telegram update error", exc_info=(type(exc), exc, exc.__traceback__))
    text = f"🚨 Bot error\n\nUnhandled {type(exc).__name__}. See application logs for details."
    for admin_id in settings.SUPER_ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Could not notify super-admin %s about bot error", admin_id)
    return True
