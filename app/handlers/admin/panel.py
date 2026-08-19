from __future__ import annotations

import logging
from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from html import escape
from app.config import settings
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.filters.admin_filter import IsAdminFilter, is_admin_of_community, is_owner_of_community
from app.keyboards.admin_kb import (
    admin_panel_keyboard, admin_root_keyboard, community_picker_keyboard, community_menu_keyboard,
    community_settings_keyboard, cleanup_keyboard, referral_settings_keyboard, danger_keyboard,
    confirm_deactivate_keyboard, admin_users_keyboard, admin_broadcast_scope_keyboard,
    admin_payment_keyboard, admin_admin_management_keyboard, admin_backup_keyboard, purchase_request_keyboard,
)
from app.keyboards.callback_data import AdminCB
from app.services import analytics_service, community_service, premium_service, referral_service
from app.keyboards.reply_kb import admin_main_reply_keyboard
from app.database.models import PurchaseRequest, PurchaseRequestStatus, CommunityAdmin, AdminRole, User
from app.services import backup_service

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
    await message.answer("Use the admin controls below.", reply_markup=admin_main_reply_keyboard())


@router.callback_query(AdminCB.filter(F.action == "root"))
async def on_root(call: CallbackQuery, session: AsyncSession) -> None:
    await call.message.edit_text("👑 <b>ADMIN</b>\n\n🛠 <b>Admin Panel</b>", reply_markup=admin_root_keyboard())
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "add_community"))
async def on_add_community(call: CallbackQuery, state: FSMContext) -> None:
    from app.filters.admin_filter import is_super_admin
    if not is_super_admin(call.from_user.id):
        await call.answer("Only the super-admin can create a new community.", show_alert=True)
        return
    from app.handlers.admin.onboarding import NewCommunity
    await state.set_state(NewCommunity.name)
    await call.message.edit_text("➕ <b>Add Community</b>\n\nSend a display name for the new community.")
    await call.answer()


@router.callback_query(AdminCB.filter(F.action.in_({"users", "broadcast", "payments", "admins", "backup", "global_settings"})))
async def on_admin_section(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    action = callback_data.action
    if action == "global_settings":
        await call.message.edit_text(
            f"⚙️ <b>Global Settings</b>\n\n"
            f"Environment: <code>{escape(settings.ENVIRONMENT)}</code>\n"
            f"Default referral target: <b>{settings.DEFAULT_REFERRAL_TARGET}</b>\n"
            f"Invite expiry: <b>{settings.INVITE_EXPIRY_HOURS} hours</b>\n\n"
            "Community-specific settings are under Communities → select community → Community Settings.",
            reply_markup=admin_root_keyboard(),
        )
        await call.answer()
        return
    communities = await _admin_communities(session, call.from_user.id)
    if not communities:
        await call.message.edit_text("No connected communities yet.", reply_markup=admin_root_keyboard())
    else:
        await call.message.edit_text(
            f"{action.replace('_', ' ').title()} — select a community:",
            reply_markup=community_picker_keyboard(communities, section=action),
        )
    await call.answer()



@router.callback_query(AdminCB.filter(F.action == "section_community"))
async def on_section_community(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    if not await is_admin_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Not authorized.", show_alert=True)
        return
    community = await community_service.get_by_id(session, callback_data.community_id)
    if community is None:
        await call.answer("Community not found.", show_alert=True)
        return

    section = callback_data.value
    if section == "users":
        await call.message.edit_text(
            f"👤 <b>User Management</b>\n\n{escape(community.name)}",
            reply_markup=admin_users_keyboard(community.id),
        )
    elif section == "broadcast":
        await call.message.edit_text(
            f"📢 <b>Broadcast</b>\n\n{escape(community.name)}\nChoose audience:",
            reply_markup=admin_broadcast_scope_keyboard(community.id),
        )
    elif section == "payments":
        await _show_pending_payments(call.message, session, community.id)
    elif section == "analytics":
        stats = await analytics_service.community_stats(session, community.id)
        await call.message.edit_text(_stats_text(community.name, stats), reply_markup=admin_root_keyboard())
    elif section == "admins":
        await call.message.edit_text(
            f"👮 <b>Admin Management</b>\n\n{escape(community.name)}",
            reply_markup=admin_admin_management_keyboard(community.id),
        )
    elif section == "backup":
        await call.message.edit_text(
            f"💾 <b>Backup & Export</b>\n\n{escape(community.name)}",
            reply_markup=admin_backup_keyboard(community.id),
        )
    await call.answer()


async def _show_pending_payments(message: Message, session: AsyncSession, community_id: int) -> None:
    pending = (await session.execute(
        select(PurchaseRequest, User)
        .join(User, User.id == PurchaseRequest.user_id)
        .where(
            PurchaseRequest.community_id == community_id,
            PurchaseRequest.status == PurchaseRequestStatus.PENDING,
        )
        .order_by(PurchaseRequest.created_at.asc())
        .limit(20)
    )).all()
    if not pending:
        await message.edit_text(
            "💳 <b>Payments</b>\n\nNo pending purchase requests.",
            reply_markup=admin_payment_keyboard(community_id),
        )
        return
    await message.edit_text(
        f"💳 <b>Payments</b>\n\nPending requests: <b>{len(pending)}</b>",
        reply_markup=admin_payment_keyboard(community_id),
    )
    for request, user in pending:
        await message.answer(
            f"🧾 <b>Purchase Request #{request.id}</b>\n\n"
            f"User: {escape(user.first_name or 'N/A')}\n"
            f"Username: @{escape(user.username) if user.username else 'N/A'}\n"
            f"Telegram ID: <code>{user.telegram_id}</code>",
            reply_markup=purchase_request_keyboard(community_id, request.id),
        )


@router.callback_query(AdminCB.filter(F.action == "broadcast_scope"))
async def on_broadcast_scope(
    call: CallbackQuery,
    callback_data: AdminCB,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not await is_admin_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Not authorized.", show_alert=True)
        return
    from app.handlers.admin.broadcast import Broadcast
    await state.update_data(community_id=callback_data.community_id, scope=("premium_only" if callback_data.value == "premium" else "all"))
    await state.set_state(Broadcast.waiting_content)
    await call.message.edit_text(
        "📢 <b>Send broadcast content</b>\n\n"
        "Send text, photo, video, GIF, or sticker.\n"
        "Optional URL button: <code>[Button](https://example.com)</code>"
    )
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "payments"))
async def on_payments(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    if callback_data.community_id:
        if not await is_admin_of_community(call.from_user.id, callback_data.community_id, session):
            await call.answer("Not authorized.", show_alert=True)
            return
        await _show_pending_payments(call.message, session, callback_data.community_id)
    else:
        communities = await _admin_communities(session, call.from_user.id)
        await call.message.edit_text(
            "💳 <b>Payments</b>\n\nSelect a community:",
            reply_markup=community_picker_keyboard(communities, section="payments"),
        )
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "user_action"))
async def on_user_action(
    call: CallbackQuery, callback_data: AdminCB, session: AsyncSession, state: FSMContext
) -> None:
    action = callback_data.value
    if action not in {"ban", "unban", "search"}:
        await call.answer("Unknown action.", show_alert=True)
        return
    if action in {"ban", "unban"}:
        authorized = await is_owner_of_community(call.from_user.id, callback_data.community_id, session)
    else:
        authorized = await is_admin_of_community(call.from_user.id, callback_data.community_id, session)
    if not authorized:
        await call.answer("Owner access required." if action in {"ban", "unban"} else "Not authorized.", show_alert=True)
        return
    await state.set_state(f"admin_user_{action}")
    await state.update_data(ui_community_id=callback_data.community_id, ui_action=action)
    prompt = {
        "ban": "🚫 Send the Telegram ID to ban.",
        "unban": "✅ Send the Telegram ID to unban.",
        "search": "🔎 Send a username (without @) or Telegram ID to search.",
    }[action]
    await call.message.answer(prompt)
    await call.answer()


@router.message(StateFilter("admin_user_ban"))
@router.message(StateFilter("admin_user_unban"))
@router.message(StateFilter("admin_user_search"))
async def on_user_action_value(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    data = await state.get_data()
    community_id = data.get("ui_community_id")
    action = data.get("ui_action")
    if not community_id or not action:
        await state.clear()
        await message.answer("Not authorized.")
        return
    if action in {"ban", "unban"}:
        authorized = await is_owner_of_community(message.from_user.id, community_id, session)
    else:
        authorized = await is_admin_of_community(message.from_user.id, community_id, session)
    if not authorized:
        await state.clear()
        await message.answer("Owner access required." if action in {"ban", "unban"} else "Not authorized.")
        return

    value = (message.text or "").strip().lstrip("@")
    if action in {"ban", "unban"} and not value.lstrip("-").isdigit():
        await message.answer("Please send a numeric Telegram ID.")
        return

    stmt = select(User).where(User.community_id == community_id)
    if value.lstrip("-").isdigit():
        stmt = stmt.where(User.telegram_id == int(value))
    else:
        stmt = stmt.where(User.username.ilike(value)).limit(1)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        await message.answer("User not found.")
        return

    community = await community_service.get_by_id(session, community_id)
    if action == "ban":
        user.is_banned = True
        user.is_premium = False
        user.joined_premium_at = None
        await session.commit()
        if community:
            await premium_service.revoke_active_invites_for_user(bot, session, community, user)
            for chat_id in (community.verification_chat_id, community.premium_chat_id):
                if chat_id:
                    try:
                        await bot.ban_chat_member(chat_id, user.telegram_id)
                    except Exception:
                        logger.exception("Could not ban user=%s chat=%s", user.telegram_id, chat_id)
        await message.answer("🚫 User banned.", reply_markup=admin_main_reply_keyboard())
    elif action == "unban":
        if community:
            for chat_id in (community.verification_chat_id, community.premium_chat_id):
                if chat_id:
                    try:
                        await bot.unban_chat_member(chat_id, user.telegram_id)
                    except Exception:
                        logger.exception("Could not unban user=%s chat=%s", user.telegram_id, chat_id)
        user.is_banned = False
        await session.commit()
        await message.answer("✅ User unbanned.", reply_markup=admin_main_reply_keyboard())
    else:
        completed = await referral_service.get_referral_progress(session, user.id)
        await message.answer(
            f"👤 <b>User</b>\n\nName: {escape(user.first_name or 'N/A')}\n"
            f"Username: @{escape(user.username) if user.username else 'N/A'}\n"
            f"ID: <code>{user.telegram_id}</code>\n"
            f"Premium: {'✅' if user.is_premium else '❌'}\n"
            f"Banned: {'🚫' if user.is_banned else 'No'}\n"
            f"Referrals: {completed}/{community.referral_target if community else '?'}",
            reply_markup=admin_main_reply_keyboard(),
        )
    await state.clear()


@router.callback_query(AdminCB.filter(F.action == "admin_action"))
async def on_admin_action(
    call: CallbackQuery, callback_data: AdminCB, session: AsyncSession, state: FSMContext
) -> None:
    if not await is_owner_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Owner access required.", show_alert=True)
        return

    if callback_data.value == "list":
        admins = (
            await session.execute(
                select(CommunityAdmin)
                .where(CommunityAdmin.community_id == callback_data.community_id)
                .order_by(CommunityAdmin.added_at.asc())
            )
        ).scalars().all()
        text = "👮 <b>Admins</b>\n\n" + (
            "\n".join(f"• <code>{a.telegram_id}</code> — {a.role.value}" for a in admins)
            or "No admins configured."
        )
        await call.message.edit_text(text, reply_markup=admin_admin_management_keyboard(callback_data.community_id))
        await call.answer()
        return

    await state.set_state("admin_manage")
    await state.update_data(ui_community_id=callback_data.community_id, ui_action=callback_data.value)
    prompt = (
        "➕ Send: <code>telegram_id</code> or <code>telegram_id moderator|owner</code>."
        if callback_data.value == "add"
        else "➖ Send the Telegram ID to remove."
    )
    await call.message.answer(prompt)
    await call.answer()


@router.message(StateFilter("admin_manage"))
async def on_admin_manage_value(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    data = await state.get_data()
    community_id = data.get("ui_community_id")
    action = data.get("ui_action")
    if not community_id or not action or not await is_owner_of_community(message.from_user.id, community_id, session):
        await state.clear()
        await message.answer("Not authorized.")
        return

    parts = (message.text or "").split()
    if not parts or not parts[0].lstrip("-").isdigit():
        await message.answer("Send a numeric Telegram ID.")
        return
    telegram_id = int(parts[0])

    if action == "add":
        role = AdminRole.MODERATOR
        if len(parts) > 1:
            if parts[1].lower() not in {"moderator", "owner"}:
                await message.answer("Role must be moderator or owner.")
                return
            role = AdminRole(parts[1].lower())

        existing = (
            await session.execute(
                select(CommunityAdmin).where(
                    CommunityAdmin.community_id == community_id,
                    CommunityAdmin.telegram_id == telegram_id,
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            if existing.role == AdminRole.OWNER and role != AdminRole.OWNER:
                await message.answer("The current owner cannot be demoted.")
                return
            existing.role = role
        else:
            if role == AdminRole.OWNER:
                owner = (
                    await session.execute(
                        select(CommunityAdmin)
                        .where(
                            CommunityAdmin.community_id == community_id,
                            CommunityAdmin.role == AdminRole.OWNER,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if owner is not None and owner.telegram_id != telegram_id:
                    await message.answer("A community can have one owner.")
                    return
            session.add(CommunityAdmin(community_id=community_id, telegram_id=telegram_id, role=role))
        await session.commit()
        from app.core.command_menu import configure_admin_commands_for_user
        await configure_admin_commands_for_user(bot, telegram_id, session)
        await message.answer("✅ Admin updated.", reply_markup=admin_main_reply_keyboard())
    else:
        existing = (
            await session.execute(
                select(CommunityAdmin).where(
                    CommunityAdmin.community_id == community_id,
                    CommunityAdmin.telegram_id == telegram_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            await message.answer("Admin not found.")
            return
        if existing.role == AdminRole.OWNER:
            owners = (
                await session.execute(
                    select(CommunityAdmin).where(
                        CommunityAdmin.community_id == community_id,
                        CommunityAdmin.role == AdminRole.OWNER,
                    )
                )
            ).scalars().all()
            if len(owners) <= 1:
                await message.answer("The community must retain one owner.")
                return
        await session.delete(existing)
        await session.commit()
        from app.core.command_menu import configure_user_commands_for_user
        await configure_user_commands_for_user(bot, telegram_id, session)
        await message.answer("✅ Admin removed.", reply_markup=admin_main_reply_keyboard())
    await state.clear()


@router.callback_query(AdminCB.filter(F.action == "backup_action"))
async def on_backup_action(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession, state: FSMContext) -> None:
    if not await is_owner_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Owner access required.", show_alert=True)
        return

    if callback_data.value == "restore":
        await state.set_state("admin_restore")
        await call.message.answer("♻️ Upload the backup JSON document now. Only a super-admin can restore data.")
        await call.answer()
        return
    elif callback_data.value == "backup":
        import json
        from aiogram.types import BufferedInputFile
        data = await backup_service.export_backup(session, callback_data.community_id)
        await call.message.answer_document(
            BufferedInputFile(
                json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"),
                filename=f"backup_community_{callback_data.community_id}.json",
            )
        )
    else:
        import csv
        import io
        from aiogram.types import BufferedInputFile
        rows = (
            await session.execute(
                select(User)
                .where(User.community_id == callback_data.community_id)
                .order_by(User.id.asc())
            )
        ).scalars().all()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["id", "telegram_id", "username", "first_name", "premium", "banned", "referral_code"])
        for u in rows:
            writer.writerow([u.id, u.telegram_id, u.username or "", u.first_name, u.is_premium, u.is_banned, u.referral_code])
        await call.message.answer_document(
            BufferedInputFile(
                out.getvalue().encode("utf-8"),
                filename=f"users_community_{callback_data.community_id}.csv",
            )
        )
    await call.answer()


@router.callback_query(AdminCB.filter(F.action == "communities"))
async def on_communities(call: CallbackQuery, callback_data: AdminCB, session: AsyncSession) -> None:
    communities = await _admin_communities(session, call.from_user.id)
    if not communities:
        await call.message.edit_text("No connected communities yet.", reply_markup=admin_root_keyboard())
    else:
        await call.message.edit_text("👥 <b>Communities</b>\n\nSelect a connected community:", reply_markup=community_picker_keyboard(communities, callback_data.page, can_add=call.from_user.id in settings.SUPER_ADMIN_IDS))
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
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Owner access required for ban/unban.")
        return
    result = await session.execute(
        select(User).where(User.community_id == community_id, User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        await message.answer("User not found in this community.")
        return
    user.is_banned = True
    user.is_premium = False
    user.joined_premium_at = None
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
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Owner access required for ban/unban.")
        return
    result = await session.execute(
        select(User).where(User.community_id == community_id, User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        await message.answer("User not found in this community.")
        return
    community = await community_service.get_by_id(session, community_id)
    if community is not None:
        for chat_id in (community.verification_chat_id, community.premium_chat_id):
            if chat_id is None:
                continue
            try:
                await message.bot.unban_chat_member(chat_id, telegram_id)
            except Exception:
                logger.exception("Could not unban user=%s from chat=%s", telegram_id, chat_id)
    user.is_banned = False
    await session.commit()
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


@router.message(IsAdminFilter(), F.text == "👥 Communities")
async def reply_admin_communities(message: Message, session: AsyncSession) -> None:
    communities = await _admin_communities(session, message.from_user.id)
    await message.answer(
        "👥 <b>Communities</b>\n\nSelect a connected community:",
        reply_markup=community_picker_keyboard(
            communities,
            can_add=message.from_user.id in settings.SUPER_ADMIN_IDS,
        ),
    )


@router.message(
    IsAdminFilter(),
    F.text.in_({
        "👤 Users",
        "📢 Broadcast",
        "💳 Payments",
        "📈 Analytics",
        "👮 Admin Management",
        "💾 Backup & Export",
        "⚙️ Global Settings",
    })
)
async def reply_admin_sections(message: Message, session: AsyncSession) -> None:
    mapping = {
        "👤 Users": "users",
        "📢 Broadcast": "broadcast",
        "💳 Payments": "payments",
        "📈 Analytics": "analytics",
        "👮 Admin Management": "admins",
        "💾 Backup & Export": "backup",
        "⚙️ Global Settings": "global_settings",
    }
    action = mapping[message.text]
    if action == "global_settings":
        await message.answer(
            f"⚙️ <b>Global Settings</b>\n\n"
            f"Environment: <code>{escape(settings.ENVIRONMENT)}</code>\n"
            f"Default referral target: <b>{settings.DEFAULT_REFERRAL_TARGET}</b>\n"
            f"Invite expiry: <b>{settings.INVITE_EXPIRY_HOURS} hours</b>",
            reply_markup=admin_main_reply_keyboard(),
        )
        return

    communities = await _admin_communities(session, message.from_user.id)
    await message.answer(
        f"{message.text}\n\nSelect a community:",
        reply_markup=community_picker_keyboard(communities, section=action),
    )
@router.message(StateFilter("admin_restore"))
async def on_admin_restore_document(message: Message, state: FSMContext, session: AsyncSession, bot: Bot) -> None:
    from app.config import settings
    if message.from_user.id not in settings.SUPER_ADMIN_IDS:
        await state.clear()
        await message.answer("Only a super-admin can restore a backup.")
        return
    document = message.document
    if document is None:
        await message.answer("Please upload the backup JSON document.")
        return
    if document.file_size and document.file_size > 10 * 1024 * 1024:
        await state.clear()
        await message.answer("Backup file is too large. Maximum supported size is 10 MB.")
        return
    file = await bot.get_file(document.file_id)
    if not file.file_path:
        await state.clear()
        await message.answer("Telegram did not provide a downloadable file path.")
        return
    buffer = await bot.download_file(file.file_path)
    import json
    try:
        data = json.loads(buffer.read())
        community = await backup_service.import_backup(session, data)
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, ValueError, TypeError, AttributeError) as exc:
        await state.clear()
        await message.answer(f"Restore failed: malformed backup ({exc}).")
        return
    await state.clear()
    await message.answer(
        f"✅ Restored community '<b>{escape(community.name)}</b>' (id={community.id}).",
        reply_markup=admin_main_reply_keyboard(),
    )


