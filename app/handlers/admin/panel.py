from __future__ import annotations

import logging
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from html import escape
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.filters.admin_filter import IsAdminFilter, is_admin_of_community, is_owner_of_community
from app.keyboards.admin_kb import (
    admin_panel_keyboard, admin_root_keyboard, community_picker_keyboard, community_menu_keyboard,
    community_settings_keyboard, cleanup_keyboard, referral_settings_keyboard, danger_keyboard,
    confirm_deactivate_keyboard,
)
from app.keyboards.callback_data import AdminCB
from app.services import analytics_service, community_service, premium_service, referral_service

router = Router(name="admin_panel")
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())
logger = logging.getLogger(__name__)


async def _admin_communities(session: AsyncSession, telegram_id: int) -> list:
    from app.config import settings
    from app.database.models import Community, CommunityAdmin

    if telegram_id in settings.SUPER_ADMIN_IDS:
        result = await session.execute(select(Community).where(Community.is_active.is_(True)))
    else:
        result = await session.execute(
            select(Community)
            .join(CommunityAdmin, CommunityAdmin.community_id == Community.id)
            .where(CommunityAdmin.telegram_id == telegram_id, Community.is_active.is_(True))
        )
    return list(result.scalars().all())


def _stats_text(name: str, s: dict) -> str:
    return (
        f"📊 <b>{escape(name)}</b>\n\n"
        f"Total users: {s['total_users']}\n"
        f"Premium users: {s['premium_users']} ({s['conversion_rate']}%)\n"
        f"Banned: {s['banned_users']}\n\n"
        f"Joins today: {s['joins_today']} | this week: {s['joins_week']}\n"
        f"Unlocks today: {s['unlocks_today']}\n\n"
        f"Referral success: {s['referral_success_rate']}% | Unlock rate: {s['unlock_rate']}%\n"
        f"Premium joins (7d): {s['premium_joins_week']}\n"
        f"Referrals completed: {s['referrals_completed']} | pending: {s['referrals_pending']}\n"
        f"Purchase requests: {s['purchase_requests']}"
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession) -> None:
    communities = await _admin_communities(session, message.from_user.id)
    if not communities:
        await message.answer("👑 <b>ADMIN</b>\n\nYou don't manage any community yet. Use /newcommunity to create one.")
        return
    await message.answer("👑 <b>ADMIN</b>\n\n🛠 <b>Admin Panel</b>", reply_markup=admin_root_keyboard())


@router.callback_query(AdminCB.filter(F.action == "root"))
async def on_root(call: CallbackQuery, session: AsyncSession) -> None:
    await call.message.edit_text("👑 <b>ADMIN</b>\n\n🛠 <b>Admin Panel</b>", reply_markup=admin_root_keyboard())
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "add_community"))
async def on_add_community(call: CallbackQuery, state: FSMContext) -> None:
    from app.handlers.admin.onboarding import NewCommunity
    await state.set_state(NewCommunity.name)
    await call.message.edit_text("➕ <b>Add Community</b>\n\nSend a display name for the new community.")
    await call.answer()


@router.callback_query(AdminCB.filter(F.action.in_({"users", "broadcast", "payments", "admins", "backup", "global_settings"})))
async def on_admin_section(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    labels = {
        "users": ("👤 Users", "Use the user-management commands from the admin command menu. Community-specific user actions require a community and target user."),
        "broadcast": ("📢 Broadcast", "Use /broadcast to start a broadcast. The existing broadcast workflow remains unchanged."),
        "payments": ("💳 Payments", "Payment requests are handled from the existing payment approval workflow."),
        "admins": ("👮 Admin Management", "Use /addadmin, /removeadmin and /listadmins. These remain restricted to authorized admins."),
        "backup": ("💾 Backup & Export", "Use /backup, /restore and /export_users from the admin command menu."),
        "global_settings": ("⚙️ Global Settings", "Global bot settings are environment-level settings. Community-specific settings are under Communities → Select Community → Community Settings."),
    }
    title, body = labels[callback_data.action]
    await call.message.edit_text(f"{title}\n\n{body}", reply_markup=admin_root_keyboard())
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "communities"))
async def on_communities(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    communities = await _admin_communities(session, call.from_user.id)
    if not communities:
        await call.message.edit_text("No connected communities yet.", reply_markup=admin_root_keyboard())
    else:
        await call.message.edit_text("👥 <b>Communities</b>\n\nSelect a connected community:", reply_markup=community_picker_keyboard(communities, callback_data.page))
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "community"))
async def on_community(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    if not await is_admin_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Not authorized for this community.", show_alert=True); return
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None or not community.is_active:
        await call.answer("Community not found.", show_alert=True); return
    await call.message.edit_text(
        f"👥 <b>{escape(community.name)}</b>\n\nSelect what you want to manage:",
        reply_markup=community_menu_keyboard(community.id),
    )
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "community_info"))
async def on_community_info(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    if not await is_admin_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Not authorized.", show_alert=True); return
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None:
        await call.answer("Community not found.", show_alert=True); return
    cleanup = getattr(community, "cleanup_frequency", "daily")
    text = (
        f"📋 <b>Community Info</b>\n\n"
        f"Name: <b>{escape(community.name)}</b>\n"
        f"ID: <code>{community.id}</code>\n"
        f"Verification chat: <code>{community.verification_chat_id}</code>\n"
        f"Premium chat: <code>{community.premium_chat_id}</code>\n"
        f"Referral target: <b>{community.referral_target}</b> successful joins\n"
        f"Cleanup: <b>{cleanup}</b>\n"
        f"Remove on Premium leave: <b>{'ON' if community.remove_on_premium_leave else 'OFF'}</b>"
    )
    await call.message.edit_text(text, reply_markup=community_menu_keyboard(community.id))
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "community_settings"))
async def on_community_settings(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    if not await is_admin_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Not authorized.", show_alert=True); return
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None:
        await call.answer("Community not found.", show_alert=True); return
    await call.message.edit_text(
        f"⚙️ <b>Community Settings</b>\n\n<b>{escape(community.name)}</b>\n\nChoose a setting:",
        reply_markup=community_settings_keyboard(community.id),
    )
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "cleanup"))
async def on_cleanup(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None or not await is_owner_of_community(call.from_user.id, community.id, session):
        await call.answer("Owner access required.", show_alert=True); return
    current = getattr(community, "cleanup_frequency", "daily") if community.delete_join_leave_messages else "disabled"
    await call.message.edit_text(
        "🧹 <b>Join/Leave Cleanup</b>\n\nChoose how often the bot runs cleanup of recent join/leave service messages.\n\nTelegram limits deletion of older messages, so the scheduler cleans eligible recent messages at the selected interval.",
        reply_markup=cleanup_keyboard(community.id, current),
    )
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "cleanup_set"))
async def on_cleanup_set(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None or not await is_owner_of_community(call.from_user.id, community.id, session):
        await call.answer("Owner access required.", show_alert=True); return
    value = callback_data.value
    if value == "now":
        from app.services.cleanup_service import cleanup_community_messages
        deleted = await cleanup_community_messages(call.bot, session, community)
        await call.answer(f"🗑 Cleaned {deleted} eligible messages.", show_alert=True)
        return
    if value == "disabled":
        community.delete_join_leave_messages = False
        community.cleanup_frequency = "disabled"
    else:
        community.delete_join_leave_messages = True
        community.cleanup_frequency = value
    await session.flush()
    await call.message.edit_text(
        f"🧹 <b>Join/Leave Cleanup</b>\n\nCurrent schedule: <b>{value}</b>",
        reply_markup=cleanup_keyboard(community.id, value),
    )
    await call.answer("Cleanup setting saved.")


@router.callback_query(AdminCB.filter(F.action == "referral_settings"))
async def on_referral_settings(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None or not await is_admin_of_community(call.from_user.id, community.id, session):
        await call.answer("Not authorized.", show_alert=True); return
    await call.message.edit_text(
        f"🎁 <b>Referral Settings</b>\n\nCurrent requirement: <b>{community.referral_target}</b> successful referred members.\n\nThis setting is per-community and is visible to admins only.",
        reply_markup=referral_settings_keyboard(community.id),
    )
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "referral_target"))
async def on_referral_target_prompt(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession, state: FSMContext) -> None:
    if not await is_owner_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Owner access required.", show_alert=True); return
    await state.set_state("admin_referral_target")
    await state.update_data(admin_community_id=callback_data.community_id)
    await call.message.answer("🎯 Send the required number of successful referrals (1–10).")
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "remove_on_leave"))
async def on_remove_on_leave(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None or not await is_owner_of_community(call.from_user.id, community.id, session):
        await call.answer("Owner access required.", show_alert=True); return
    community.remove_on_premium_leave = not community.remove_on_premium_leave
    await session.flush()
    await call.message.edit_text(
        f"🚪 <b>Remove on Leave</b>\n\nStatus: <b>{'ON' if community.remove_on_premium_leave else 'OFF'}</b>",
        reply_markup=community_settings_keyboard(community.id),
    )
    await call.answer("Setting updated.")


@router.callback_query(AdminCB.filter(F.action == "danger"))
async def on_danger(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    community = await community_service.get_by_id(session, callback_data.community_id, )
    if community is None or not await is_owner_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Owner access required.", show_alert=True); return
    await call.message.edit_text("⚠️ <b>Danger Zone</b>\n\nThese actions can affect community access.", reply_markup=danger_keyboard(community.id))
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "deactivate"))
async def on_deactivate_prompt(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    if not await is_owner_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Owner access required.", show_alert=True); return
    await call.message.edit_text("⚠️ <b>Deactivate this community?</b>\n\nThis hides it from normal bot flows. Existing database records are preserved.", reply_markup=confirm_deactivate_keyboard(callback_data.community_id))
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "deactivate_confirm"))
async def on_deactivate_confirm(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    if not await is_owner_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Owner access required.", show_alert=True); return
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None:
        await call.answer("Community not found.", show_alert=True); return
    community.is_active = False
    await session.flush()
    await call.message.edit_text("✅ Community deactivated.", reply_markup=admin_root_keyboard())
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "panel"))
async def on_panel(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    await on_community(call, AdminCB(action="community", community_id=callback_data.community_id, page=callback_data.page), session)


@router.callback_query(AdminCB.filter(F.action == "settings"))
async def on_settings(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    await on_community_settings(call, AdminCB(action="community_settings", community_id=callback_data.community_id), session)


@router.callback_query(AdminCB.filter(F.action == "analytics"))
async def on_analytics(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    if callback_data.community_id:
        community = await community_service.get_by_id(session, callback_data.community_id)
        if community is not None:
            stats = await analytics_service.community_stats(session, community.id)
            await call.answer(f"Conversion: {stats['conversion_rate']}%\nUnlocks today: {stats['unlocks_today']}\nReferrals completed: {stats['referrals_completed']}", show_alert=True)
            return
    await call.message.edit_text("📈 <b>Analytics</b>\n\nSelect a community to view detailed statistics.", reply_markup=community_picker_keyboard(await _admin_communities(session, call.from_user.id)))
    await call.answer()


@router.message(Command("ban"))
async def cmd_ban(message: Message, session: AsyncSession, bot: Bot) -> None:
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].lstrip("-").isdigit():
        await message.answer("Usage: /ban <community_id> <telegram_id>")
        return
    community_id, telegram_id = int(parts[1]), int(parts[2])
    if not await is_admin_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    result = await session.execute(
        select(User).where(User.community_id == community_id, User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        await message.answer("User not found in this community.")
        return
    user.is_banned = True
    community = await community_service.get_by_id(session, community_id)
    await session.commit()
    if community is not None:
        await premium_service.revoke_active_invites_for_user(bot, session, community, user)
        for chat_id in (community.verification_chat_id, community.premium_chat_id):
            if chat_id is None:
                continue
            try:
                await bot.ban_chat_member(chat_id, telegram_id)
            except Exception:
                logger.exception("Could not remove banned user=%s from chat=%s", telegram_id, chat_id)
    await message.answer(f"🚫 Banned {escape(user.first_name or str(telegram_id))} (id={telegram_id}).")


@router.message(Command("unban"))
async def cmd_unban(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].lstrip("-").isdigit():
        await message.answer("Usage: /unban <community_id> <telegram_id>")
        return
    community_id, telegram_id = int(parts[1]), int(parts[2])
    if not await is_admin_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    result = await session.execute(
        select(User).where(User.community_id == community_id, User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        await message.answer("User not found in this community.")
        return
    user.is_banned = False
    await session.flush()
    await message.answer(f"✅ Unbanned {escape(user.first_name or str(telegram_id))} (id={telegram_id}).")


@router.message(Command("search"))
async def cmd_search(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer("Usage: /search <community_id> <username or telegram_id>")
        return
    community_id, query = int(parts[1]), parts[2].lstrip("@").strip()
    if not await is_admin_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return

    stmt = select(User).where(User.community_id == community_id)
    if query.isdigit():
        stmt = stmt.where(User.telegram_id == int(query))
    else:
        stmt = stmt.where(User.username.ilike(f"%{query}%"))
    result = await session.execute(stmt.limit(10))
    users = result.scalars().all()
    if not users:
        await message.answer("No matching users.")
        return

    from sqlalchemy import func
    from app.database.models import PendingReferral, ReferralStatus

    progress = await session.execute(
        select(PendingReferral.referrer_user_id, func.count(PendingReferral.id))
        .where(
            PendingReferral.referrer_user_id.in_([u.id for u in users]),
            PendingReferral.status == ReferralStatus.COUNTED,
        )
        .group_by(PendingReferral.referrer_user_id)
    )
    progress_map = dict(progress.all())
    lines = []
    for u in users:
        completed = progress_map.get(u.id, 0)
        lines.append(
            f"• {u.first_name or 'N/A'} (@{u.username or '—'}, id={u.telegram_id})\n"
            f"  Premium: {'✅' if u.is_premium else '❌'} | Banned: {'🚫' if u.is_banned else 'no'} | "
            f"Referrals: {completed}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("analytics"))
async def cmd_analytics(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /analytics <community_id>")
        return
    community_id = int(parts[1])
    if not await is_admin_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await message.answer("Community not found.")
        return
    stats = await analytics_service.community_stats(session, community_id)
    top = "\n".join(
        f"{i+1}. {escape(x['name'])} — {x['referrals']} referrals"
        for i, x in enumerate(stats["most_active_users"])
    ) or "No referral activity yet."
    await message.answer(
        f"📈 <b>{escape(community.name)} analytics</b>\n\n"
        f"Daily joins: {stats['joins_today']}\n"
        f"Weekly joins: {stats['joins_week']}\n"
        f"Referral conversion: {stats['referral_success_rate']}%\n"
        f"Unlock rate: {stats['unlock_rate']}%\n"
        f"Premium joins (7d): {stats['premium_joins_week']}\n\n"
        f"<b>Most active referrers</b>\n{top}"
    )
