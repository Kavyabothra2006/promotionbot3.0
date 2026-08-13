from __future__ import annotations

import json
from html import escape

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.filters.admin_filter import IsAdminFilter, is_owner_of_community
from app.services import backup_service

router = Router(name="admin_backup")
router.message.filter(IsAdminFilter())


@router.message(Command("backup"))
async def cmd_backup(message: Message, command: CommandObject, session: AsyncSession, bot: Bot) -> None:
    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Usage: /backup <community_id>")
        return
    community_id = int(args)
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return

    try:
        data = await backup_service.export_backup(session, community_id)
    except ValueError:
        await message.answer("Community not found.")
        return

    payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    file = BufferedInputFile(payload, filename=f"backup_community_{community_id}.json")
    await message.answer_document(file, caption=f"💾 Backup for community {community_id}")


@router.message(Command("restore"))
async def cmd_restore(message: Message, session: AsyncSession, bot: Bot) -> None:
    """Reply to the backup.json document with /restore"""
    target = message.reply_to_message
    if target is None or target.document is None:
        await message.answer("Reply to a backup.json file with /restore")
        return
    if not message.from_user or message.from_user.id not in settings.SUPER_ADMIN_IDS:
        await message.answer("Only a super-admin can restore a backup (it can create/overwrite a community).")
        return

    if target.document.file_size and target.document.file_size > 10 * 1024 * 1024:
        await message.answer("Backup file is too large. Maximum supported size is 10 MB.")
        return
    file = await bot.get_file(target.document.file_id)
    if not file.file_path:
        await message.answer("Telegram did not provide a downloadable file path.")
        return
    buffer = await bot.download_file(file.file_path)
    try:
        data = json.loads(buffer.read())
    except (json.JSONDecodeError, UnicodeDecodeError):
        await message.answer("That file isn't valid JSON.")
        return

    try:
        community = await backup_service.import_backup(session, data)
    except (KeyError, ValueError) as e:
        await message.answer(f"Restore failed: backup file is malformed ({e}).")
        return

    await message.answer(f"✅ Restored community '{escape(community.name)}' (id={community.id}).")

@router.message(Command("export_users"))
async def cmd_export_users(message: Message, command: CommandObject, session: AsyncSession) -> None:
    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Usage: /export_users <community_id>")
        return
    community_id = int(args)
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    from app.database.models import User
    import csv, io
    result = await session.execute(select(User).where(User.community_id == community_id).order_by(User.id.asc()))
    rows = list(result.scalars().all())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "telegram_id", "username", "first_name", "premium", "banned", "joined_verification_at", "joined_premium_at", "referral_code"])
    for user in rows:
        writer.writerow([
            user.id, user.telegram_id, user.username or "", user.first_name, user.is_premium, user.is_banned,
            user.joined_verification_at.isoformat() if user.joined_verification_at else "",
            user.joined_premium_at.isoformat() if user.joined_premium_at else "",
            user.referral_code,
        ])
    await message.answer_document(
        BufferedInputFile(output.getvalue().encode("utf-8"), filename=f"users_community_{community_id}.csv"),
        caption=f"👥 User export for community {community_id} ({len(rows)} users)",
    )
