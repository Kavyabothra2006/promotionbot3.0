from __future__ import annotations

import logging
from html import escape
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Community, PurchaseRequest, PurchaseRequestStatus, User
from app.keyboards.callback_data import MenuCB, ReferralCB, PurchaseCB
from app.keyboards.reply_kb import user_main_reply_keyboard
from app.keyboards.user_kb import (
    instant_access_keyboard,
    referral_link_keyboard,
    referral_menu_keyboard,
    verification_menu_keyboard,
)
from app.services import admin_service, community_service, referral_service
from app.keyboards.admin_kb import purchase_request_keyboard

logger = logging.getLogger(__name__)
router = Router(name="verification")


def _progress_bar(completed: int, target: int) -> str:
    filled = min(completed, target)
    return "🟩" * filled + "⬜" * max(target - filled, 0)


async def _verification_text(user: User, completed: int, target: int) -> str:
    name = escape(user.first_name or "there")
    return (
        f"Hey {name}! Choose how you would like to unlock Premium.\n\n"
        f"Referral progress: {_progress_bar(completed, target)} {completed}/{target}"
    )


async def show_verification_menu(message: Message, session: AsyncSession, community: Community, user: User) -> None:
    completed = await referral_service.get_referral_progress(session, user.id)
    text = await _verification_text(user, completed, community.referral_target)
    await message.answer(
        text,
        reply_markup=verification_menu_keyboard(completed, community.referral_target, community.id),
    )
    await message.answer("🎁 Referral & Help are available from the menu.", reply_markup=user_main_reply_keyboard())


async def _resolve_active_user(
    call: CallbackQuery, session: AsyncSession, community_id: int
) -> tuple[Community, User] | None:
    """Resolve exactly the community encoded in the callback; never fall back to the first community."""
    community = await community_service.get_by_id(session, community_id)
    if community is None or not community.is_active:
        await call.answer("This community is unavailable.", show_alert=True)
        return None

    membership = await session.execute(
        select(User.id).where(User.community_id == community_id, User.telegram_id == call.from_user.id)
    )
    if membership.scalar_one_or_none() is None:
        await call.answer("You are not registered for this community.", show_alert=True)
        return None
    user = await referral_service.get_or_create_user(
        session, community.id, call.from_user.id, call.from_user.username, call.from_user.first_name
    )
    if user.is_banned:
        await call.answer("You've been banned from this community.", show_alert=True)
        return None
    return community, user


@router.callback_query(MenuCB.filter(F.action == "back_main"))
async def on_back_main(call: CallbackQuery, callback_data: MenuCB, session: AsyncSession) -> None:
    resolved = await _resolve_active_user(call, session, callback_data.community_id)
    if resolved is None:
        return
    community, user_row = resolved
    completed = await referral_service.get_referral_progress(session, user_row.id)
    text = await _verification_text(user_row, completed, community.referral_target)
    await call.message.edit_text(
        text, reply_markup=verification_menu_keyboard(completed, community.referral_target, community.id)
    )
    await call.answer()


@router.callback_query(MenuCB.filter(F.action == "choose_referral"))
async def on_choose_referral(call: CallbackQuery, callback_data: MenuCB, session: AsyncSession) -> None:
    resolved = await _resolve_active_user(call, session, callback_data.community_id)
    if resolved is None:
        return
    community, _ = resolved

    text = (
        "📤 <b>Refer & Unlock</b>\n\n"
        "Invite friends using your personal referral link.\n"
        "When they join and the required number is reached, Premium unlocks automatically."
    )
    await call.message.edit_text(text, reply_markup=referral_menu_keyboard(community.id))
    await call.answer()


@router.callback_query(ReferralCB.filter(F.action == "get_link"))
async def on_get_link(call: CallbackQuery, callback_data: ReferralCB, session: AsyncSession, bot: Bot) -> None:
    resolved = await _resolve_active_user(call, session, callback_data.community_id)
    if resolved is None:
        return
    community, user = resolved
    me = await bot.get_me()
    link = await referral_service.build_referral_link(me.username, user.referral_code)
    completed = await referral_service.get_referral_progress(session, user.id)

    text = (
        f"🔗 <b>Your referral link:</b>\n<code>{escape(link)}</code>\n\n"
        f"Progress: {_progress_bar(completed, community.referral_target)} {completed}/{community.referral_target}"
    )
    await call.message.edit_text(text, reply_markup=referral_link_keyboard(link, community.id))
    await call.answer()


@router.callback_query(ReferralCB.filter(F.action == "check_progress"))
async def on_check_progress(call: CallbackQuery, callback_data: ReferralCB, session: AsyncSession) -> None:
    resolved = await _resolve_active_user(call, session, callback_data.community_id)
    if resolved is None:
        return
    community, user = resolved
    completed = await referral_service.get_referral_progress(session, user.id)
    await call.answer(f"Progress: {completed}/{community.referral_target}", show_alert=True)


@router.callback_query(MenuCB.filter(F.action == "choose_instant"))
async def on_choose_instant(call: CallbackQuery, callback_data: MenuCB, session: AsyncSession, bot: Bot) -> None:
    resolved = await _resolve_active_user(call, session, callback_data.community_id)
    if resolved is None:
        return
    community, user = resolved
    user = (
        await session.execute(
            select(User).where(User.id == user.id).with_for_update()
        )
    ).scalar_one()

    if user.is_premium:
        await call.answer("You already have Premium.", show_alert=True)
        return

    existing_result = await session.execute(
        select(PurchaseRequest).where(
            PurchaseRequest.community_id == community.id,
            PurchaseRequest.user_id == user.id,
            PurchaseRequest.status.in_([PurchaseRequestStatus.DRAFT, PurchaseRequestStatus.PENDING]),
        ).with_for_update()
    )
    existing_request = existing_result.scalar_one_or_none()
    if existing_request is None:
        existing_request = PurchaseRequest(community_id=community.id, user_id=user.id, status=PurchaseRequestStatus.DRAFT)
        session.add(existing_request)
        await session.flush()

    admin_id = await admin_service.get_primary_admin_id(session, community.id)
    admin_username = None
    if admin_id is not None:
        try:
            chat = await bot.get_chat(admin_id)
            admin_username = chat.username
        except TelegramAPIError:
            admin_username = None

    prefill = (
        "Hello! I would like to purchase Premium access.\n\n"
        f"Name: {user.first_name}\n"
        f"Username: @{user.username if user.username else 'N/A'}\n"
        f"User ID: {user.telegram_id}\n\n"
        "Please send payment details."
    )

    if admin_username:
        admin_url = f"https://t.me/{admin_username}?text={quote(prefill)}"
        text = "Want Premium instantly?\n\nPurchase Premium manually from our admin below."
        await call.message.edit_text(text, reply_markup=instant_access_keyboard(admin_url, community.id, existing_request.id))
    else:
        await call.message.edit_text(
            "Want Premium instantly? I could not build a direct admin link. Start a chat with the bot admin and then confirm below."
        )

    await call.answer("Open the admin chat, send the prepared request, then confirm below.")

@router.callback_query(PurchaseCB.filter(F.action == "sent"))
async def on_purchase_request_sent(call: CallbackQuery, callback_data: PurchaseCB, session: AsyncSession, bot: Bot) -> None:
    resolved = await _resolve_active_user(call, session, callback_data.community_id)
    if resolved is None:
        return
    community, user = resolved
    request = (await session.execute(
        select(PurchaseRequest).where(
            PurchaseRequest.id == callback_data.request_id,
            PurchaseRequest.community_id == community.id,
            PurchaseRequest.user_id == user.id,
        ).with_for_update()
    )).scalar_one_or_none()
    if request is None:
        await call.answer("Request not found.", show_alert=True)
        return
    if request.status == PurchaseRequestStatus.DRAFT:
        request.status = PurchaseRequestStatus.PENDING
        await session.commit()
        request_text = (
            f"🧾 <b>Pending Premium purchase</b>\n\n"
            f"Community: {escape(community.name)}\n"
            f"User: {escape(user.first_name)}\n"
            f"Username: @{escape(user.username) if user.username else 'N/A'}\n"
            f"Telegram ID: <code>{user.telegram_id}</code>"
        )
        for admin_target in await admin_service.list_admin_ids(session, community.id):
            try:
                await bot.send_message(admin_target, request_text, reply_markup=purchase_request_keyboard(community.id, request.id))
            except TelegramAPIError:
                logger.debug("Could not send purchase action to admin %s", admin_target)
        await call.answer("Purchase request sent to admins.", show_alert=True)
    else:
        await call.answer("Your request is already pending.", show_alert=True)
    return

@router.callback_query(MenuCB.filter(F.action == "help"))
async def on_help(call: CallbackQuery, callback_data: MenuCB, session: AsyncSession) -> None:
    resolved = await _resolve_active_user(call, session, callback_data.community_id)
    if resolved is None:
        return
    community, _user = resolved
    await call.message.edit_text(
        "❓ <b>How to get access</b>\n\n"
        "1. Tap <b>🎁 Get Access</b>.\n"
        "2. Share your personal referral link.\n"
        f"3. Bring <b>{community.referral_target}</b> successful members into the verification group.\n"
        "4. You will receive a notification when each referral is counted.\n"
        "5. When you reach the target, your Premium access is unlocked.",
        reply_markup=referral_menu_keyboard(community.id),
    )
    await call.answer()
