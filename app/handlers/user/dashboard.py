from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import community_service, referral_service
from app.keyboards.callback_data import MenuCB
from app.keyboards.user_kb import dashboard_keyboard

router = Router(name="dashboard")


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message, session: AsyncSession, bot: Bot) -> None:
    communities = await community_service.find_user_communities(session, message.from_user.id)
    active = [c for c in communities if c.is_active]
    if not active:
        await message.answer("No active community is linked to your account yet. Join a verification group first.")
        return

    bot_info = await bot.get_me()
    lines = ["📋 <b>Your Premium Dashboard</b>"]
    for community in active:
        user = await referral_service.get_or_create_user(
            session, community.id, message.from_user.id, message.from_user.username, message.from_user.first_name
        )
        completed = await referral_service.get_referral_progress(session, user.id)
        remaining = max(community.referral_target - completed, 0)
        lines.append(
            f"\n<b>{escape(community.name)}</b>\n"
            f"Referral progress: {completed}/{community.referral_target} (remaining {remaining})\n"
            f"Premium: {'✅ Active' if user.is_premium else '❌ Not active'}\n"
            f"Referral link: https://t.me/{bot_info.username}?start={user.referral_code}"
        )

    community = active[0] if len(active) == 1 else None
    await message.answer(
        "\n".join(lines),
        reply_markup=dashboard_keyboard(community.id) if community else None,
    )


@router.callback_query(MenuCB.filter(F.action == "dashboard"))
async def on_dashboard(call: CallbackQuery, callback_data: MenuCB, session: AsyncSession, bot: Bot) -> None:
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None or not community.is_active:
        await call.answer("This community is unavailable.", show_alert=True)
        return

    user = await referral_service.get_or_create_user(
        session,
        community.id,
        call.from_user.id,
        call.from_user.username,
        call.from_user.first_name,
    )
    if user.is_banned:
        await call.answer("You've been banned from this community.", show_alert=True)
        return

    completed = await referral_service.get_referral_progress(session, user.id)
    bot_info = await bot.get_me()
    remaining = max(community.referral_target - completed, 0)
    text = (
        "📊 <b>My Dashboard</b>\n\n"
        f"🏠 <b>{escape(community.name)}</b>\n"
        f"📈 Referral progress: {completed}/{community.referral_target}\n"
        f"🎯 Remaining: {remaining}\n"
        f"💎 Premium: {'✅ Active' if user.is_premium else '❌ Not active'}\n\n"
        f"🔗 Referral link:\n<code>https://t.me/{bot_info.username}?start={user.referral_code}</code>"
    )
    await call.message.edit_text(text, reply_markup=dashboard_keyboard(community.id))
    await call.answer()

