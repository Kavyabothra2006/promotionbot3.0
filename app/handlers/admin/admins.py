from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AdminRole, CommunityAdmin
from app.filters.admin_filter import IsAdminFilter, is_owner_of_community
from app.services import community_service

router = Router(name="admin_admins")
router.message.filter(IsAdminFilter())


def _args(command: CommandObject) -> tuple[int, int, AdminRole | None] | None:
    parts = (command.args or "").split()
    if len(parts) not in (2, 3) or not parts[0].isdigit() or not parts[1].lstrip("-").isdigit():
        return None
    role = None
    if len(parts) == 3:
        try:
            role = AdminRole(parts[2].lower())
        except ValueError:
            return None
    return int(parts[0]), int(parts[1]), role


@router.message(Command("addadmin"))
async def add_admin(message: Message, command: CommandObject, session: AsyncSession) -> None:
    parsed = _args(command)
    if parsed is None:
        await message.answer("Usage: /addadmin <community_id> <telegram_id> [moderator|owner]")
        return
    community_id, telegram_id, role = parsed
    if role is None:
        role = AdminRole.MODERATOR
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Only the community owner can manage admins.")
        return
    if await community_service.get_by_id(session, community_id) is None:
        await message.answer("Community not found.")
        return
    if role == AdminRole.OWNER:
        existing_owner = (await session.execute(select(CommunityAdmin).where(
            CommunityAdmin.community_id == community_id,
            CommunityAdmin.role == AdminRole.OWNER,
        ).limit(1))).scalar_one_or_none()
        if existing_owner is not None and existing_owner.telegram_id != telegram_id:
            await message.answer("A community must have one owner. Remove/transfer the current owner before assigning a new owner.")
            return
    existing = (await session.execute(select(CommunityAdmin).where(
        CommunityAdmin.community_id == community_id,
        CommunityAdmin.telegram_id == telegram_id,
    ))).scalar_one_or_none()
    if existing is not None:
        existing.role = role
    else:
        session.add(CommunityAdmin(community_id=community_id, telegram_id=telegram_id, role=role))
    await message.answer(f"✅ Admin {telegram_id} set to {role.value} for community {community_id}.")


@router.message(Command("removeadmin"))
async def remove_admin(message: Message, command: CommandObject, session: AsyncSession) -> None:
    parsed = _args(command)
    if parsed is None:
        await message.answer("Usage: /removeadmin <community_id> <telegram_id>")
        return
    community_id, telegram_id, _role = parsed
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Only the community owner can manage admins.")
        return
    existing = (await session.execute(select(CommunityAdmin).where(
        CommunityAdmin.community_id == community_id,
        CommunityAdmin.telegram_id == telegram_id,
    ))).scalar_one_or_none()
    if existing is None:
        await message.answer("That user is not an admin of this community.")
        return
    if existing.role == AdminRole.OWNER:
        owners = (await session.execute(select(CommunityAdmin).where(
            CommunityAdmin.community_id == community_id,
            CommunityAdmin.role == AdminRole.OWNER,
        ))).scalars().all()
        if len(owners) <= 1:
            await message.answer("The community must retain at least one owner.")
            return
    await session.delete(existing)
    await message.answer(f"✅ Removed admin {telegram_id} from community {community_id}.")


@router.message(Command("listadmins"))
async def list_admins(message: Message, command: CommandObject, session: AsyncSession) -> None:
    community_id = int((command.args or "0").strip()) if (command.args or "0").strip().isdigit() else 0
    if not community_id:
        await message.answer("Usage: /listadmins <community_id>")
        return
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    admins = (await session.execute(select(CommunityAdmin).where(
        CommunityAdmin.community_id == community_id
    ).order_by(CommunityAdmin.added_at.asc()))).scalars().all()
    if not admins:
        await message.answer("No community admins configured.")
        return
    await message.answer("👮 Community admins:\n\n" + "\n".join(f"• {a.telegram_id} — {a.role.value}" for a in admins))
