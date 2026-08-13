from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, Router
from aiogram.filters.chat_member_updated import JOIN_TRANSITION, LEAVE_TRANSITION, ChatMemberUpdatedFilter
from aiogram.types import ChatJoinRequest, ChatMemberUpdated
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.services import admin_service, community_service, premium_service

logger = logging.getLogger(__name__)
router = Router(name="premium_membership")


@router.chat_join_request()
async def on_premium_join_request(event: ChatJoinRequest, session: AsyncSession, bot: Bot) -> None:
    # Only our Premium communities are handled; unrelated join requests are ignored.
    community = await community_service.get_by_premium_chat(session, event.chat.id)
    if community is None:
        return
    await premium_service.handle_premium_join_request(bot, session, event)


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_premium_join(event: ChatMemberUpdated, session: AsyncSession, bot: Bot) -> None:
    joined_user = event.new_chat_member.user
    if joined_user.is_bot:
        return
    community = await community_service.get_by_premium_chat(session, event.chat.id)
    if community is None:
        return

    user_row = (
        await session.execute(
            select(User).where(User.community_id == community.id, User.telegram_id == joined_user.id).with_for_update()
        )
    ).scalar_one_or_none()
    if user_row is None:
        logger.warning("Unknown user %s joined Premium community=%s", joined_user.id, community.id)
        try:
            await bot.ban_chat_member(community.premium_chat_id, joined_user.id)
        except Exception:
            logger.exception("Could not remove unknown Premium member %s", joined_user.id)
        return

    if user_row.is_banned:
        await premium_service.revoke_active_invites_for_user(bot, session, community, user_row)
        try:
            await bot.ban_chat_member(community.premium_chat_id, joined_user.id)
        except Exception:
            logger.exception("Could not remove banned Premium member %s", joined_user.id)
        return

    activated = await premium_service.mark_invite_used_and_revoke(bot, session, community, user_row)
    if not activated:
        # Manual membership entry must never become Premium access accidentally.
        try:
            await bot.ban_chat_member(community.premium_chat_id, joined_user.id)
        except Exception:
            logger.exception("Could not remove unauthorized Premium member %s", joined_user.id)
        await admin_service.notify_admins(
            bot, session, community.id,
            f"🚫 Unauthorized Premium join by <code>{joined_user.id}</code> was removed.",
        )
        return

    await admin_service.notify_admins(
        bot,
        session,
        community.id,
        f"✅ Premium joined: {escape(user_row.first_name or str(user_row.telegram_id))} joined the Premium group.",
    )


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def on_premium_leave(event: ChatMemberUpdated, session: AsyncSession, bot: Bot) -> None:
    left_user = event.old_chat_member.user
    if left_user.is_bot:
        return
    community = await community_service.get_by_premium_chat(session, event.chat.id)
    if community is None:
        return

    user_row = (
        await session.execute(
            select(User).where(User.community_id == community.id, User.telegram_id == left_user.id)
        )
    ).scalar_one_or_none()
    if user_row is None:
        return

    if community.remove_on_premium_leave and user_row.is_premium:
        user_row.is_premium = False
        user_row.joined_premium_at = None
        await admin_service.notify_admins(
            bot,
            session,
            community.id,
            f"⚠️ {escape(user_row.first_name or str(user_row.telegram_id))} left Premium and was marked non-premium.",
        )
