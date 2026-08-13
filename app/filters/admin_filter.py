from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import AdminRole, CommunityAdmin


async def get_community_role(session: AsyncSession, telegram_id: int, community_id: int) -> AdminRole | None:
    if telegram_id in settings.SUPER_ADMIN_IDS:
        return AdminRole.OWNER
    result = await session.execute(
        select(CommunityAdmin.role).where(
            CommunityAdmin.telegram_id == telegram_id,
            CommunityAdmin.community_id == community_id,
        )
    )
    return result.scalar_one_or_none()


async def is_admin_of_community(telegram_id: int, community_id: int, session: AsyncSession) -> bool:
    return telegram_id in settings.SUPER_ADMIN_IDS or await get_community_role(session, telegram_id, community_id) is not None


async def is_owner_of_community(telegram_id: int, community_id: int, session: AsyncSession) -> bool:
    return telegram_id in settings.SUPER_ADMIN_IDS or await get_community_role(session, telegram_id, community_id) == AdminRole.OWNER


def is_super_admin(telegram_id: int) -> bool:
    return telegram_id in settings.SUPER_ADMIN_IDS


class IsSuperAdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user is not None and is_super_admin(event.from_user.id)


class IsAdminFilter(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        user = event.from_user
        if user is None:
            return False
        if user.id in settings.SUPER_ADMIN_IDS:
            return True
        result = await session.execute(
            select(CommunityAdmin.id).where(CommunityAdmin.telegram_id == user.id).limit(1)
        )
        return result.scalar_one_or_none() is not None
