from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CleanupMessage, Community

logger = logging.getLogger(__name__)

FREQUENCY = {"daily": timedelta(days=1), "3days": timedelta(days=3), "weekly": timedelta(days=7)}


async def track_cleanup_message(session: AsyncSession, community: Community, chat_id: int, message_id: int) -> None:
    if not community.delete_join_leave_messages or community.cleanup_frequency == "disabled":
        return
    session.add(CleanupMessage(community_id=community.id, chat_id=chat_id, message_id=message_id))
    await session.flush()


async def cleanup_community_messages(bot: Bot, session: AsyncSession, community: Community) -> int:
    rows = (await session.execute(
        select(CleanupMessage).where(CleanupMessage.community_id == community.id).order_by(CleanupMessage.created_at.asc()).limit(500)
    )).scalars().all()
    deleted = 0
    now = datetime.now(timezone.utc)
    # Telegram's deletion window is limited; only attempt messages that can still be deleted.
    cutoff = now - timedelta(hours=47)
    for row in rows:
        if row.created_at and row.created_at < cutoff:
            await session.delete(row)
            continue
        try:
            await bot.delete_message(row.chat_id, row.message_id)
            deleted += 1
            await session.delete(row)
        except TelegramAPIError:
            # Keep a still-eligible message tracked so transient Telegram/API
            # failures can be retried on the next scheduled cleanup. Once a
            # message is outside Telegram's deletion window, the row is removed
            # above because it can no longer be made deletable.
            logger.warning(
                "Could not delete cleanup message chat=%s message=%s; keeping it for retry",
                row.chat_id,
                row.message_id,
            )
    await session.flush()
    return deleted


async def cleanup_scheduler_loop(bot: Bot, session_factory) -> None:
    while True:
        try:
            async with session_factory() as session:
                communities = (await session.execute(
                    select(Community).where(Community.is_active.is_(True), Community.delete_join_leave_messages.is_(True))
                )).scalars().all()
                now = datetime.now(timezone.utc)
                for community in communities:
                    delta = FREQUENCY.get(community.cleanup_frequency)
                    if delta is None:
                        continue
                    last = community.cleanup_last_run_at
                    scheduled_run_due = last is None or now - last >= delta
                    # Telegram's deletion window is shorter than the optional 3-day
                    # and weekly schedules. Sweep messages approaching expiry so they
                    # are deleted before they become permanently undeletable.
                    expiry_cutoff = now - timedelta(hours=44)
                    expiring = (
                        await session.execute(
                            select(CleanupMessage.id)
                            .where(
                                CleanupMessage.community_id == community.id,
                                CleanupMessage.created_at <= expiry_cutoff,
                                CleanupMessage.created_at > now - timedelta(hours=47),
                            )
                            .limit(1)
                        )
                    ).scalar_one_or_none() is not None
                    if scheduled_run_due or expiring:
                        await cleanup_community_messages(bot, session, community)
                        if scheduled_run_due:
                            community.cleanup_last_run_at = now
                await session.commit()
        except Exception:
            logger.exception("Cleanup scheduler failed")
        # Hourly resolution is enough; the selected schedule controls the actual cadence.
        import asyncio
        await asyncio.sleep(3600)
