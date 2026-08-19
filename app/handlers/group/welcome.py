from __future__ import annotations

import logging
from html import escape
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.chat_member_updated import JOIN_TRANSITION, LEAVE_TRANSITION, ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.models import Community, MediaType, User
from app.keyboards.user_kb import welcome_keyboard
from app.services import community_service, premium_service, referral_service

logger = logging.getLogger(__name__)
router = Router(name="group_welcome")


async def _send_group_welcome(bot: Bot, community: Community, user: User) -> None:
    me = await bot.get_me()
    display_name = user.first_name or (f"@{user.username}" if user.username else "there")
    try:
        member_count = await bot.get_chat_member_count(community.verification_chat_id)
    except TelegramAPIError:
        member_count = "?"
    values = {
        "name": display_name,
        "username": f"@{user.username}" if user.username else display_name,
        "group": community.name,
        "member_count": str(member_count),
    }
    template = community.welcome_text
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    # Admin-entered welcome text is treated as literal text; profile/community values are
    # never allowed to inject HTML into the globally HTML-parsed bot output.
    caption = escape(template)
    kb = welcome_keyboard(community.welcome_button_text, me.username, community.id)
    chat_id = community.verification_chat_id
    media_type = community.welcome_media_type
    file_id = community.welcome_media_file_id

    try:
        if media_type in {MediaType.PHOTO, MediaType.VIDEO, MediaType.ANIMATION} and file_id:
            if len(caption) <= 1024:
                if media_type == MediaType.PHOTO:
                    await bot.send_photo(chat_id, file_id, caption=caption, reply_markup=kb)
                elif media_type == MediaType.VIDEO:
                    await bot.send_video(chat_id, file_id, caption=caption, reply_markup=kb)
                else:
                    await bot.send_animation(chat_id, file_id, caption=caption, reply_markup=kb)
            else:
                # Telegram limits media captions to 1024 characters. Preserve the
                # configured welcome text instead of losing the whole welcome on an API error.
                if media_type == MediaType.PHOTO:
                    await bot.send_photo(chat_id, file_id)
                elif media_type == MediaType.VIDEO:
                    await bot.send_video(chat_id, file_id)
                else:
                    await bot.send_animation(chat_id, file_id)
                await bot.send_message(chat_id, caption, reply_markup=kb)
        elif media_type == MediaType.STICKER and file_id:
            await bot.send_sticker(chat_id, file_id)
            await bot.send_message(chat_id, caption, reply_markup=kb)
        else:
            await bot.send_message(chat_id, caption, reply_markup=kb)
    except TelegramAPIError:
        logger.exception("Failed to send welcome message in community=%s", community.id)


@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_group_join(event: ChatMemberUpdated, session: AsyncSession, bot: Bot) -> None:
    new_user = event.new_chat_member.user
    if new_user.is_bot:
        return

    community = await community_service.get_by_verification_chat(session, event.chat.id)
    if community is None:
        return  # not one of our managed verification groups

    user_row = await referral_service.get_or_create_user(
        session, community.id, new_user.id, new_user.username, new_user.first_name
    )
    if user_row.is_banned:
        logger.info("Ignoring join from banned user %s in community %s", new_user.id, community.id)
        return
    if not user_row.has_joined_verification_group:
        user_row.has_joined_verification_group = True
        user_row.joined_verification_at = datetime.now(timezone.utc)

    await premium_service.handle_referral_confirmation(bot, session, community, new_user.id)
    await _send_group_welcome(bot, community, user_row)

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def on_group_leave(event: ChatMemberUpdated, session: AsyncSession, bot: Bot) -> None:
    left_user = event.old_chat_member.user
    if left_user.is_bot:
        return
    community = await community_service.get_by_verification_chat(session, event.chat.id)
    if community is None:
        return
    user_row = (
        await session.execute(
            select(User).where(
                User.community_id == community.id, User.telegram_id == left_user.id
            )
        )
    ).scalar_one_or_none()
    if user_row is None:
        return
    user_row.has_joined_verification_group = False
    # Referral credit is intentionally not revoked automatically: once a referral is
    # counted, removing it based on a transient leave would make the reward exploitable.
    if user_row.referred_by_user_id:
        referrer = await session.get(User, user_row.referred_by_user_id)
        if referrer is not None:
            try:
                await bot.send_message(
                    referrer.telegram_id,
                    f"ℹ️ <b>{escape(left_user.first_name or 'Your friend')}</b> left the verification group in "
                    f"<b>{escape(community.name)}</b>.\n\n"
                    "Your completed referral count has not been removed.",
                )
            except TelegramAPIError:
                logger.debug("Could not send referral leave notification to %s", referrer.telegram_id)
