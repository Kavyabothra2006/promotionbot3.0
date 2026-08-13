from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from app.database.base import async_session_factory
from app.database.models import Community, User

logger = logging.getLogger(__name__)
RECONCILE_INTERVAL_SECONDS = 3600
BATCH_SIZE = 100


async def reconcile_once(bot: Bot) -> None:
    async with async_session_factory() as session:
        communities = (await session.execute(select(Community).where(
            Community.is_active.is_(True),
            Community.remove_on_premium_leave.is_(True),
            Community.premium_chat_id.is_not(None),
        ))).scalars().all()
        for community in communities:
            last_id = 0
            while True:
                users = (await session.execute(
                    select(User).where(
                        User.community_id == community.id,
                        User.is_premium.is_(True),
                        User.id > last_id,
                    ).order_by(User.id.asc()).limit(BATCH_SIZE)
                )).scalars().all()
                if not users:
                    break
                for user in users:
                    last_id = user.id
                    try:
                        member = await bot.get_chat_member(community.premium_chat_id, user.telegram_id)
                    except TelegramAPIError:
                        logger.warning("Could not reconcile premium membership community=%s user=%s", community.id, user.telegram_id)
                        continue
                    if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
                        user.is_premium = False
                        user.joined_premium_at = None
                await session.commit()


async def membership_reconcile_loop(bot: Bot) -> None:
    while True:
        try:
            await reconcile_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Premium membership reconciliation failed")
        await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)
