from __future__ import annotations

from aiogram import Bot, Router
from html import escape
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import AdminRole, Community, CommunityAdmin
from app.filters.admin_filter import IsSuperAdminFilter

router = Router(name="onboarding")


class NewCommunity(StatesGroup):
    name = State()
    verification_chat = State()
    premium_chat = State()
    referral_target = State()


async def _resolve_admin_chat_id(bot: Bot, message: Message) -> tuple[int | None, str]:
    """Accepts either a forwarded message from the target chat, or a raw numeric chat id.
    Confirms the bot is an admin there before accepting it."""
    chat_id: int | None = None
    if message.forward_from_chat is not None:
        chat_id = message.forward_from_chat.id
    elif message.text and message.text.strip().lstrip("-").isdigit():
        chat_id = int(message.text.strip())

    if chat_id is None:
        return None, "Please forward a message from that group, or send its numeric chat ID."

    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
    except TelegramAPIError:
        return None, "I can't see that chat. Make sure I've been added to it first."

    if member.status == "creator":
        return chat_id, ""
    if member.status != "administrator":
        return None, "I'm in that chat but not an admin there yet. Promote me to admin and try again."
    required = []
    for attr in ("can_invite_users", "can_restrict_members", "can_delete_messages"):
        if not getattr(member, attr, False):
            required.append(attr.replace("can_", "").replace("_", " "))
    if required:
        return None, "I am an admin, but I am missing required permissions: " + ", ".join(required) + ". Please update my Telegram admin permissions."

    return chat_id, ""


@router.message(Command("newcommunity"), IsSuperAdminFilter())
async def start_new_community(message: Message, state: FSMContext) -> None:
    await state.set_state(NewCommunity.name)
    await message.answer("Let's set up a new community. Send a display name for it (e.g. 'Crypto Signals VIP').")


@router.message(StateFilter(NewCommunity.name))
async def set_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Please send a text name.")
        return
    await state.update_data(name=name)
    await state.set_state(NewCommunity.verification_chat)
    await message.answer(
        "Now add me as <b>admin</b> to your <b>verification group</b>, then forward any message "
        "from that group here (or send its numeric chat ID)."
    )


@router.message(StateFilter(NewCommunity.verification_chat))
async def set_verification_chat(message: Message, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    chat_id, error = await _resolve_admin_chat_id(bot, message)
    if error:
        await message.answer(error)
        return

    existing = await session.execute(select(Community.id).where(Community.verification_chat_id == chat_id))
    if existing.scalar_one_or_none() is not None:
        await message.answer("That group is already registered as a verification group for another community.")
        return

    try:
        link = await bot.create_chat_invite_link(chat_id=chat_id, name="Community Invite")
        invite_link = link.invite_link
    except TelegramAPIError:
        await message.answer("I verified the group, but I could not create its verification invite. Check my invite-link permission and try again.")
        return

    await state.update_data(verification_chat_id=chat_id, verification_invite_link=invite_link)
    await state.set_state(NewCommunity.premium_chat)
    await message.answer(
        "Got it. Now add me as <b>admin</b> to your <b>premium group</b>, then forward a message "
        "from it here (or send its numeric chat ID)."
    )


@router.message(StateFilter(NewCommunity.premium_chat))
async def set_premium_chat(message: Message, state: FSMContext, bot: Bot, session: AsyncSession) -> None:
    chat_id, error = await _resolve_admin_chat_id(bot, message)
    if error:
        await message.answer(error)
        return

    existing = await session.execute(select(Community.id).where(Community.premium_chat_id == chat_id))
    if existing.scalar_one_or_none() is not None:
        await message.answer("That group is already registered as a premium group for another community.")
        return

    await state.update_data(premium_chat_id=chat_id)
    await state.set_state(NewCommunity.referral_target)
    await message.answer(
        f"How many successful referrals should unlock Premium? Send a number 1-10, "
        f"or 'skip' to use the default ({settings.DEFAULT_REFERRAL_TARGET})."
    )


@router.message(StateFilter(NewCommunity.referral_target))
async def set_referral_target(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip().lower()
    if text == "skip":
        target = settings.DEFAULT_REFERRAL_TARGET
    elif text.isdigit() and 1 <= int(text) <= 10:
        target = int(text)
    else:
        await message.answer("Send a number 1-10, or 'skip'.")
        return

    data = await state.get_data()
    community = Community(
        name=data["name"],
        verification_chat_id=data["verification_chat_id"],
        premium_chat_id=data["premium_chat_id"],
        verification_invite_link=data.get("verification_invite_link"),
        referral_target=target,
    )
    session.add(community)
    await session.flush()

    session.add(CommunityAdmin(community_id=community.id, telegram_id=message.from_user.id, role=AdminRole.OWNER))
    await session.flush()

    await state.clear()
    await message.answer(
        f"✅ Community '<b>{escape(community.name)}</b>' created (id={community.id}). "
        f"You're now its owner admin. Use /admin to manage it."
    )
