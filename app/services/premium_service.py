from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    Community,
    PremiumInvite,
    PremiumInviteStatus,
    UnlockFeedMessage,
    UnlockMethod,
    User,
)
from app.keyboards.user_kb import join_premium_keyboard
from app.services import admin_service, referral_service

logger = logging.getLogger(__name__)
MAX_UNLOCK_FEED_MESSAGES = 10


async def create_one_time_invite(bot: Bot, chat_id: int) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.INVITE_EXPIRY_HOURS)
    # Join requests make the link recipient-controlled by the bot: a forwarded link
    # cannot silently grant access to the wrong person.
    link = await bot.create_chat_invite_link(
        chat_id=chat_id,
        expire_date=expires_at,
        creates_join_request=True,
    )
    return link.invite_link, expires_at


async def post_unlock_feed(bot: Bot, session: AsyncSession, community: Community, user: User) -> None:
    display_name = user.first_name.strip() or (f"@{user.username}" if user.username else "A user")
    text = f"🎉 {escape(display_name)} has successfully completed verification and unlocked Premium! 🔓"
    try:
        msg = await bot.send_message(community.verification_chat_id, text)
    except TelegramAPIError:
        logger.exception("Failed to post unlock feed message community=%s", community.id)
        return

    session.add(UnlockFeedMessage(community_id=community.id, chat_id=msg.chat.id, message_id=msg.message_id))
    await session.commit()

    result = await session.execute(
        select(UnlockFeedMessage)
        .where(UnlockFeedMessage.community_id == community.id)
        .order_by(UnlockFeedMessage.created_at.desc())
        .offset(MAX_UNLOCK_FEED_MESSAGES)
    )
    stale = list(result.scalars().all())
    for row in stale:
        try:
            await bot.delete_message(row.chat_id, row.message_id)
        except TelegramAPIError:
            pass
        await session.delete(row)
    if stale:
        await session.commit()


async def unlock_premium(
    bot: Bot,
    session: AsyncSession,
    community: Community,
    user: User,
    method: UnlockMethod,
) -> PremiumInvite | None:
    """Create a recipient-validated Premium join-request invite.

    The database is committed before external notifications are sent. Telegram-created
    invites are revoked if the database insert fails, preventing orphaned access links.
    """
    if community.premium_chat_id is None:
        logger.error("Community %s has no premium_chat_id", community.id)
        return None

    locked = (
        await session.execute(select(User).where(User.id == user.id).with_for_update())
    ).scalar_one()
    if locked.is_banned or locked.is_premium:
        return None

    now = datetime.now(timezone.utc)
    active = (
        await session.execute(
            select(PremiumInvite)
            .where(
                PremiumInvite.community_id == community.id,
                PremiumInvite.user_id == locked.id,
                PremiumInvite.status == PremiumInviteStatus.ACTIVE,
                ((PremiumInvite.expires_at > now) | (PremiumInvite.approved_at.is_not(None))),
            )
            .order_by(PremiumInvite.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        return active

    expired = (
        await session.execute(
            select(PremiumInvite)
            .where(
                PremiumInvite.community_id == community.id,
                PremiumInvite.user_id == locked.id,
                PremiumInvite.status == PremiumInviteStatus.ACTIVE,
            )
            .with_for_update()
        )
    ).scalars().all()
    for old in expired:
        try:
            await bot.revoke_chat_invite_link(community.premium_chat_id, old.invite_link)
        except TelegramAPIError:
            logger.warning("Could not revoke old Premium invite %s; continuing with a new invite", old.id)
        old.status = PremiumInviteStatus.EXPIRED
        old.revoked_at = now
    if expired:
        await session.commit()

    try:
        invite_link, expires_at = await create_one_time_invite(bot, community.premium_chat_id)
    except TelegramAPIError:
        logger.exception("Could not create Premium invite for user=%s", locked.id)
        return None

    invite = PremiumInvite(
        community_id=community.id,
        user_id=locked.id,
        invite_link=invite_link,
        status=PremiumInviteStatus.ACTIVE,
        expires_at=expires_at,
    )
    session.add(invite)
    locked.premium_unlocked_at = locked.premium_unlocked_at or now
    locked.premium_unlock_method = method
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        try:
            await bot.revoke_chat_invite_link(community.premium_chat_id, invite_link)
        except TelegramAPIError:
            logger.exception("Failed to revoke orphaned Premium invite after DB failure")
        # Another concurrent unlock may have won the unique active-invite race.
        existing = await get_active_invite_for_user(session, community.id, locked.id)
        if existing is not None:
            return existing
        raise

    try:
        await bot.send_message(
            locked.telegram_id,
            "🎉 <b>Congratulations!</b>\n\nYou have successfully unlocked Premium.\nClick below to request access.",
            reply_markup=join_premium_keyboard(invite_link),
        )
    except TelegramAPIError:
        logger.warning("Could not DM user %s about Premium invite", locked.telegram_id)

    await post_unlock_feed(bot, session, community, locked)
    await admin_service.notify_admins(
        bot,
        session,
        community.id,
        f"🔓 Premium unlocked for {escape(locked.first_name or str(locked.telegram_id))} "
        f"via {method.value}.",
    )
    return invite


async def handle_premium_join_request(bot: Bot, session: AsyncSession, event) -> None:
    user = event.from_user
    if user.is_bot:
        return
    from app.services.community_service import get_by_premium_chat

    community = await get_by_premium_chat(session, event.chat.id)
    if community is None or community.premium_chat_id is None:
        return

    if event.invite_link is None:
        await bot.decline_chat_join_request(event.chat.id, user.id)
        return

    row = (
        await session.execute(
            select(PremiumInvite)
            .join(User, User.id == PremiumInvite.user_id)
            .where(
                PremiumInvite.community_id == community.id,
                PremiumInvite.invite_link == event.invite_link.invite_link,
                PremiumInvite.status == PremiumInviteStatus.ACTIVE,
                PremiumInvite.expires_at > datetime.now(timezone.utc),
                User.telegram_id == user.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()

    if row is None:
        await bot.decline_chat_join_request(event.chat.id, user.id)
        await admin_service.notify_admins(
            bot, session, community.id,
            f"🚫 Unauthorized Premium join request from <code>{user.id}</code> was declined.",
        )
        return

    await bot.approve_chat_join_request(event.chat.id, user.id)
    # Approval itself is the durable Premium entitlement. The later chat_member event
    # only confirms physical membership and marks the invite used.
    now = datetime.now(timezone.utc)
    invited_user = (await session.execute(select(User).where(User.id == row.user_id).with_for_update())).scalar_one()
    if not invited_user.is_premium:
        invited_user.is_premium = True
        invited_user.premium_unlocked_at = invited_user.premium_unlocked_at or now
        if invited_user.premium_unlock_method == UnlockMethod.NONE:
            invited_user.premium_unlock_method = UnlockMethod.REFERRAL
    row.approved_at = now
    await session.commit()


async def get_active_invite_for_user(session: AsyncSession, community_id: int, user_id: int) -> PremiumInvite | None:
    now = datetime.now(timezone.utc)
    return (
        await session.execute(
            select(PremiumInvite)
            .where(
                PremiumInvite.community_id == community_id,
                PremiumInvite.user_id == user_id,
                PremiumInvite.status == PremiumInviteStatus.ACTIVE,
                PremiumInvite.expires_at > now,
            )
            .order_by(PremiumInvite.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def handle_referral_confirmation(bot: Bot, session: AsyncSession, community: Community, telegram_id: int) -> None:
    result = await referral_service.confirm_referral_on_join(session, community, telegram_id)
    if result is None:
        return
    referrer, completed = result
    await session.commit()
    await admin_service.notify_admins(
        bot, session, community.id,
        f"👥 New referral counted for {escape(referrer.first_name or str(referrer.telegram_id))}: "
        f"{completed}/{community.referral_target}.",
    )
    # Personalized user notification: the referrer should immediately know that a friend
    # completed the verification-group join and that the referral counted.
    try:
        await bot.send_message(
            referrer.telegram_id,
            f"🎉 <b>1 friend joined!</b>\n\n"
            f"Your referral progress is now <b>{completed}/{community.referral_target}</b> for "
            f"<b>{escape(community.name)}</b>."
            + ("\n\n🔓 You reached the required referrals. Your access is being prepared." if completed >= community.referral_target and not referrer.is_premium else ""),
        )
    except Exception:
        logger.debug("Could not send referral-count notification to %s", referrer.telegram_id)
    if not referrer.is_premium and completed >= community.referral_target:
        invite = await unlock_premium(bot, session, community, referrer, UnlockMethod.REFERRAL)
        if invite is not None:
            await bot.send_message(
                referrer.telegram_id,
                f"🎉 Referral target complete: {completed}/{community.referral_target}! Premium access unlocked.",
            )
            return
    try:
        await bot.send_message(referrer.telegram_id, f"✅ Referral progress: {completed}/{community.referral_target}")
    except TelegramAPIError:
        pass


async def expire_stale_invites(bot: Bot, session: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(PremiumInvite, Community.premium_chat_id)
        .join(Community, Community.id == PremiumInvite.community_id)
        .where(PremiumInvite.status == PremiumInviteStatus.ACTIVE, PremiumInvite.expires_at < now)
        .with_for_update(skip_locked=True)
    )
    rows = result.all()
    revoked = 0
    for invite, chat_id in rows:
        if chat_id is not None:
            try:
                await bot.revoke_chat_invite_link(chat_id=chat_id, invite_link=invite.invite_link)
            except TelegramAPIError:
                logger.warning("Could not revoke expired Premium invite %s", invite.id)
                continue
        invite.status = PremiumInviteStatus.EXPIRED
        invite.revoked_at = now
        revoked += 1
    await session.commit()
    return revoked


async def revoke_active_invites_for_user(bot: Bot, session: AsyncSession, community: Community, user: User) -> int:
    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(PremiumInvite)
            .where(
                PremiumInvite.community_id == community.id,
                PremiumInvite.user_id == user.id,
                PremiumInvite.status == PremiumInviteStatus.ACTIVE,
            )
            .with_for_update()
        )
    ).scalars().all()
    revoked = 0
    for invite in rows:
        try:
            if community.premium_chat_id is not None:
                await bot.revoke_chat_invite_link(community.premium_chat_id, invite.invite_link)
        except TelegramAPIError:
            logger.warning("Could not revoke Premium invite %s", invite.id)
            continue
        invite.status = PremiumInviteStatus.REVOKED
        invite.revoked_at = now
        revoked += 1
    await session.commit()
    return revoked


async def mark_invite_used_and_revoke(bot: Bot, session: AsyncSession, community: Community, user: User) -> bool:
    now = datetime.now(timezone.utc)
    invite = (
        await session.execute(
            select(PremiumInvite)
            .where(
                PremiumInvite.community_id == community.id,
                PremiumInvite.user_id == user.id,
                PremiumInvite.status == PremiumInviteStatus.ACTIVE,
                ((PremiumInvite.expires_at > now) | (PremiumInvite.approved_at.is_not(None))),
            )
            .order_by(PremiumInvite.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if invite is None or user.is_banned:
        return False

    invite.status = PremiumInviteStatus.USED
    invite.used_at = now
    invite.revoked_at = now
    user.is_premium = True
    user.premium_unlocked_at = user.premium_unlocked_at or now
    user.joined_premium_at = user.joined_premium_at or now
    try:
        if community.premium_chat_id is not None:
            await bot.revoke_chat_invite_link(community.premium_chat_id, invite.invite_link)
    except TelegramAPIError:
        logger.warning("Could not revoke used Premium invite %s", invite.id)
    await session.commit()
    return True


async def retry_pending_referral_unlocks(bot: Bot) -> int:
    """Retry earned Premium entitlements after transient Telegram/API failures."""
    from app.database.base import async_session_factory

    unlocked = 0
    async with async_session_factory() as session:
        communities = (await session.execute(
            select(Community).where(Community.is_active.is_(True), Community.premium_chat_id.is_not(None))
        )).scalars().all()
        for community in communities:
            last_id = 0
            while True:
                users = (await session.execute(
                    select(User).where(
                        User.community_id == community.id,
                        User.is_premium.is_(False),
                        User.is_banned.is_(False),
                        User.has_joined_verification_group.is_(True),
                        User.premium_unlock_method.in_([UnlockMethod.NONE, UnlockMethod.REFERRAL]),
                        User.id > last_id,
                    ).order_by(User.id.asc()).limit(100)
                )).scalars().all()
                if not users:
                    break
                for user in users:
                    last_id = user.id
                    completed = await referral_service.get_referral_progress(session, user.id)
                    if completed < community.referral_target:
                        continue
                    active_invite = await get_active_invite_for_user(session, community.id, user.id)
                    if active_invite is not None:
                        continue
                    invite = await unlock_premium(bot, session, community, user, UnlockMethod.REFERRAL)
                    if invite is not None:
                        unlocked += 1
        await session.commit()
    return unlocked
