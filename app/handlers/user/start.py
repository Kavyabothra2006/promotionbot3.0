from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.user.verification import show_verification_menu
from app.services import admin_service, community_service, premium_service, referral_service

logger = logging.getLogger(__name__)
router = Router(name="start")

GENERIC_START_TEXT = (
    "👋 Hi! I manage Premium access for one or more communities.\n\n"
    "To get started, join the community group you were invited to — I'll greet you there "
    "with a button to begin verification."
)


@router.message(CommandStart(deep_link=True))
async def on_start_deep_link(message: Message, command: CommandObject, session: AsyncSession, bot: Bot) -> None:
    payload = (command.args or "").strip()
    user = message.from_user

    if payload.startswith("verify_"):
        try:
            community_id = int(payload.removeprefix("verify_"))
        except ValueError:
            await message.answer(GENERIC_START_TEXT)
            return
        community = await community_service.get_by_id(session, community_id)
        if community is None or not community.is_active:
            await message.answer("This community is no longer available.")
            return
        user_row = await referral_service.get_or_create_user(session, community.id, user.id, user.username, user.first_name)
        if user_row.is_banned:
            await message.answer("You've been banned from this community.")
            return
        await show_verification_menu(message, session, community, user_row)
        return

    community = await referral_service.resolve_community_by_referral_code(session, payload)
    if community is None:
        await message.answer(GENERIC_START_TEXT)
        return

    accepted, reason, _pending = await referral_service.register_referral_click(
        session,
        community,
        referrer_code=payload,
        referred_telegram_id=user.id,
        referred_username=user.username,
        referred_is_bot=user.is_bot,
    )

    if reason == "self":
        await message.answer("You can't use your own referral link 🙂")
        return
    if reason == "bot":
        await message.answer(GENERIC_START_TEXT)
        return
    if reason == "invalid_code":
        await message.answer("That referral link looks invalid or expired.")
        return
    if reason == "duplicate":
        await message.answer("Looks like you've already been referred by someone else here.")
        return
    if accepted:
        await admin_service.notify_admins(
            bot, session, community.id,
            f"👤 New referral: {escape(user.first_name or str(user.id))} was invited to {escape(community.name)}.",
        )
        join_hint = (
            f"\n\nJoin the group to complete verification: {community.verification_invite_link}"
            if community.verification_invite_link
            else "\n\nJoin the community group to complete verification and help your friend unlock Premium!"
        )
        await message.answer(
            "🎉 You've been invited! Once you join the community group, your friend gets credit "
            "towards unlocking Premium." + join_hint
        )

    # Fix the missed-join edge case: if this user had already joined before clicking the
    # referral link, run the normal transactional join-confirmation path immediately.
    user_row = await referral_service.get_or_create_user(session, community.id, user.id, user.username, user.first_name)
    if user_row.is_banned:
        return
    if accepted and reason in {"pending_created", "pending_joined"} and user_row.has_joined_verification_group:
        await premium_service.handle_referral_confirmation(bot, session, community, user.id)
        user_row = await referral_service.get_or_create_user(session, community.id, user.id, user.username, user.first_name)
    await show_verification_menu(message, session, community, user_row)


@router.message(CommandStart())
async def on_start_plain(message: Message, session: AsyncSession) -> None:
    communities = await community_service.find_user_communities(session, message.from_user.id)
    if not communities:
        await message.answer(GENERIC_START_TEXT)
        return

    active_non_banned = []
    for community in communities:
        user_row = await referral_service.get_or_create_user(
            session, community.id, message.from_user.id, message.from_user.username, message.from_user.first_name
        )
        if not user_row.is_banned:
            active_non_banned.append((community, user_row))

    if not active_non_banned:
        await message.answer("You've been banned from all communities currently linked to this account.")
        return
    if len(active_non_banned) > 1:
        names = "\n".join(f"• {c.name} (community {c.id})" for c, _ in active_non_banned)
        await message.answer(
            "You belong to multiple communities. Open the verification link for the community you want to manage.\n\n" + names
        )
        return

    community, user_row = active_non_banned[0]
    await show_verification_menu(message, session, community, user_row)


@router.message(Command("getaccess"))
async def on_get_access(message: Message, session: AsyncSession) -> None:
    communities = await community_service.find_user_communities(session, message.from_user.id)
    active = []
    for community in communities:
        user_row = await referral_service.get_or_create_user(session, community.id, message.from_user.id, message.from_user.username, message.from_user.first_name)
        if not user_row.is_banned:
            active.append((community, user_row))
    if not active:
        await message.answer("Join the verification community first, then use 🎁 Get Access again.")
        return
    if len(active) == 1:
        await show_verification_menu(message, session, active[0][0], active[0][1])
        return
    names = "\n".join(f"• {c.name}" for c, _ in active)
    await message.answer("🎁 <b>Get Access</b>\n\nYou are linked to multiple communities:\n\n" + names + "\n\nOpen the community's verification link to continue.")

@router.message(Command("help"))
async def on_help_command(message: Message) -> None:
    await message.answer(
        "❓ <b>Help</b>\n\n"
        "Use <b>🎁 Get Access</b> to generate your personal referral link.\n"
        "When your invited friends join the verification group, you will receive a personalized notification.\n"
        "Reach the community's referral target to unlock Premium access."
    )
