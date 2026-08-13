from __future__ import annotations

from html import escape

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import community_service, referral_service

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

    await message.answer("\n".join(lines))
