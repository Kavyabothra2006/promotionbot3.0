from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import AdminRole, CommunityAdmin

logger = logging.getLogger(__name__)


async def list_admin_ids(session: AsyncSession, community_id: int) -> list[int]:
    result = await session.execute(
        select(CommunityAdmin.telegram_id).where(CommunityAdmin.community_id == community_id)
    )
    ids = list(result.scalars().all())
    # super-admins implicitly manage every community too
    for admin_id in settings.SUPER_ADMIN_IDS:
        if admin_id not in ids:
            ids.append(admin_id)
    return ids


async def get_primary_admin_id(session: AsyncSession, community_id: int) -> int | None:
    result = await session.execute(
        select(CommunityAdmin.telegram_id)
        .where(CommunityAdmin.community_id == community_id, CommunityAdmin.role == AdminRole.OWNER)
        .order_by(CommunityAdmin.added_at.asc())
        .limit(1)
    )
    owner = result.scalar_one_or_none()
    if owner is not None:
        return owner

    result = await session.execute(
        select(CommunityAdmin.telegram_id)
        .where(CommunityAdmin.community_id == community_id)
        .order_by(CommunityAdmin.added_at.asc())
        .limit(1)
    )
    fallback = result.scalar_one_or_none()
    if fallback is not None:
        return fallback

    return settings.SUPER_ADMIN_IDS[0] if settings.SUPER_ADMIN_IDS else None


async def notify_admins(bot: Bot, session: AsyncSession, community_id: int, text: str) -> None:
    for admin_id in await list_admin_ids(session, community_id):
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError:
            logger.debug("Could not notify admin %s (may not have started the bot)", admin_id)
