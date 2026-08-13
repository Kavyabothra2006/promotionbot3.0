from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Community


async def get_by_verification_chat(session: AsyncSession, chat_id: int) -> Community | None:
    result = await session.execute(
        select(Community).where(Community.verification_chat_id == chat_id, Community.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_by_premium_chat(session: AsyncSession, chat_id: int) -> Community | None:
    result = await session.execute(
        select(Community).where(Community.premium_chat_id == chat_id, Community.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, community_id: int) -> Community | None:
    return await session.get(Community, community_id)


async def find_user_communities(session: AsyncSession, telegram_id: int) -> list[Community]:
    """Communities where this Telegram user has an active User record (used to route /start
    when a user belongs to more than one community, e.g. for the dashboard)."""
    from app.database.models import User  # local import avoids a circular import at module load

    result = await session.execute(
        select(Community)
        .join(User, User.community_id == Community.id)
        .where(User.telegram_id == telegram_id, Community.is_active.is_(True))
    )
    return list(result.scalars().all())
