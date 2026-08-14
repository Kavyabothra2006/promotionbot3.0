from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault, MenuButtonCommands
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import CommunityAdmin

USER_COMMANDS = [
    BotCommand(command="start", description="🏠 Start"),
    BotCommand(command="referral", description="🎁 Referral"),
    BotCommand(command="help", description="❓ Help"),
]

ADMIN_COMMANDS = [
    BotCommand(command="start", description="🏠 Start"),
    BotCommand(command="admin", description="🛠 Admin Panel"),
    BotCommand(command="newcommunity", description="➕ Add Community"),
    BotCommand(command="broadcast", description="📢 Broadcast"),
    BotCommand(command="analytics", description="📈 Analytics"),
    BotCommand(command="ban", description="🚫 Ban User"),
    BotCommand(command="unban", description="✅ Unban User"),
    BotCommand(command="search", description="🔎 Search User"),
    BotCommand(command="addadmin", description="➕ Add Admin"),
    BotCommand(command="removeadmin", description="➖ Remove Admin"),
    BotCommand(command="listadmins", description="📋 List Admins"),
    BotCommand(command="backup", description="💾 Backup"),
    BotCommand(command="restore", description="♻️ Restore"),
    BotCommand(command="export_users", description="📤 Export Users"),
    BotCommand(command="setwelcometext", description="👋 Welcome Message"),
    BotCommand(command="setwelcomebutton", description="🔘 Welcome Button"),
    BotCommand(command="setreferraltarget", description="🎯 Referral Target"),
    BotCommand(command="setwelcomemedia", description="🖼 Welcome Media"),
    BotCommand(command="toggleleavecleanup", description="🧹 Join/Leave Cleanup"),
    BotCommand(command="toggleremoveonleave", description="🚪 Remove on Leave"),
    BotCommand(command="help", description="❓ Help"),
]


async def configure_command_menus(bot: Bot, session: AsyncSession) -> None:
    await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    for telegram_id in settings.SUPER_ADMIN_IDS:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=telegram_id))
        except Exception:
            continue
    ids = (await session.execute(select(CommunityAdmin.telegram_id).distinct())).scalars().all()
    for telegram_id in ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=telegram_id))
        except Exception:
            continue


async def configure_admin_commands_for_user(bot: Bot, telegram_id: int) -> None:
    try:
        await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=telegram_id))
    except Exception:
        return


async def configure_user_commands_for_user(bot: Bot, telegram_id: int) -> None:
    try:
        await bot.set_my_commands(USER_COMMANDS, scope=BotCommandScopeChat(chat_id=telegram_id))
    except Exception:
        return
