from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import MediaType
from app.filters.admin_filter import IsAdminFilter, is_owner_of_community
from app.services import community_service

router = Router(name="admin_settings")
router.message.filter(IsAdminFilter())


def _split_id_and_rest(command: CommandObject) -> tuple[int, str] | None:
    args = (command.args or "").strip()
    if not args:
        return None
    parts = args.split(maxsplit=1)
    if not parts[0].isdigit():
        return None
    community_id = int(parts[0])
    rest = parts[1] if len(parts) > 1 else ""
    return community_id, rest


@router.message(Command("setwelcometext"))
async def set_welcome_text(message: Message, command: CommandObject, session: AsyncSession) -> None:
    parsed = _split_id_and_rest(command)
    if not parsed or not parsed[1]:
        await message.answer("Usage: /setwelcometext <community_id> <text>\nSupports {name} {username} {group} {member_count}.")
        return
    community_id, text = parsed
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await message.answer("Community not found.")
        return
    community.welcome_text = text
    await session.flush()
    await message.answer("✅ Welcome text updated.")


@router.message(Command("setwelcomebutton"))
async def set_welcome_button(message: Message, command: CommandObject, session: AsyncSession) -> None:
    parsed = _split_id_and_rest(command)
    if not parsed or not parsed[1]:
        await message.answer("Usage: /setwelcomebutton <community_id> <button text>")
        return
    community_id, text = parsed
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await message.answer("Community not found.")
        return
    community.welcome_button_text = text[:64]
    await session.flush()
    await message.answer("✅ Welcome button text updated.")


@router.message(Command("setreferraltarget"))
async def set_referral_target(message: Message, command: CommandObject, session: AsyncSession) -> None:
    parsed = _split_id_and_rest(command)
    if not parsed or not parsed[1].isdigit() or not (1 <= int(parsed[1]) <= 10):
        await message.answer("Usage: /setreferraltarget <community_id> <1-10>")
        return
    community_id, value = parsed
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await message.answer("Community not found.")
        return
    community.referral_target = int(value)
    await session.flush()
    await message.answer(f"✅ Referral target set to {value}.")


@router.message(Command("setwelcomemedia"))
async def set_welcome_media(message: Message, command: CommandObject, session: AsyncSession) -> None:
    """Reply to a photo/video/animation/sticker with: /setwelcomemedia <community_id>"""
    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Reply to a photo/video/GIF/sticker with: /setwelcomemedia <community_id>")
        return
    community_id = int(args)
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    target = message.reply_to_message
    if target is None:
        await message.answer("Reply to the media message with this command.")
        return

    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await message.answer("Community not found.")
        return

    if target.photo:
        community.welcome_media_type = MediaType.PHOTO
        community.welcome_media_file_id = target.photo[-1].file_id
    elif target.video:
        community.welcome_media_type = MediaType.VIDEO
        community.welcome_media_file_id = target.video.file_id
    elif target.animation:
        community.welcome_media_type = MediaType.ANIMATION
        community.welcome_media_file_id = target.animation.file_id
    elif target.sticker:
        community.welcome_media_type = MediaType.STICKER
        community.welcome_media_file_id = target.sticker.file_id
    else:
        await message.answer("Unsupported media type. Use photo, video, GIF, or sticker.")
        return

    await session.flush()
    await message.answer("✅ Welcome media updated (stored as file_id only, no local storage).")


@router.message(Command("toggleleavecleanup"))
async def toggle_cleanup(message: Message, command: CommandObject, session: AsyncSession) -> None:
    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Usage: /toggleleavecleanup <community_id>")
        return
    community_id = int(args)
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await message.answer("Community not found.")
        return
    community.delete_join_leave_messages = not community.delete_join_leave_messages
    await session.flush()
    await message.answer(f"✅ Join/leave message cleanup: {'ON' if community.delete_join_leave_messages else 'OFF'}")


@router.message(Command("toggleremoveonleave"))
async def toggle_remove_on_leave(message: Message, command: CommandObject, session: AsyncSession) -> None:
    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Usage: /toggleremoveonleave <community_id>")
        return
    community_id = int(args)
    if not await is_owner_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await message.answer("Community not found.")
        return
    community.remove_on_premium_leave = not community.remove_on_premium_leave
    await session.flush()
    await message.answer(f"✅ Remove-on-premium-leave: {'ON' if community.remove_on_premium_leave else 'OFF'}")

# ---------------------------------------------------------------------------
# Inline community-settings UX
# ---------------------------------------------------------------------------
from aiogram import F
from aiogram.fsm.context import FSMContext
from app.keyboards.admin_kb import community_settings_keyboard, referral_settings_keyboard
from app.keyboards.callback_data import AdminCB
from app.database.models import Community
from app.filters.admin_filter import is_admin_of_community


@router.callback_query(AdminCB.filter(F.action == "welcome_text"))
async def ui_welcome_text(call, callback_data: AdminCB, session: AsyncSession, state: FSMContext) -> None:
    if not await is_owner_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Owner access required.", show_alert=True); return
    await state.set_state("community_welcome_text")
    await state.update_data(community_id=callback_data.community_id)
    await call.message.answer(
        "👋 <b>Welcome Message</b>\n\nSend the new welcome message.\n\nSupported variables: <code>{name}</code> <code>{username}</code> <code>{group}</code> <code>{member_count}</code>"
    )
    await call.answer()


@router.message(StateFilter("community_welcome_text"))
async def ui_welcome_text_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data(); community_id = data.get("community_id")
    if not community_id or not await is_owner_of_community(message.from_user.id, community_id, session):
        await state.clear(); return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send text only."); return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await state.clear(); await message.answer("Community not found."); return
    community.welcome_text = text
    await session.flush(); await state.clear()
    await message.answer("✅ Welcome message updated.", reply_markup=community_settings_keyboard(community_id))


@router.callback_query(AdminCB.filter(F.action == "welcome_button"))
async def ui_welcome_button(call, callback_data: AdminCB, session: AsyncSession, state: FSMContext) -> None:
    if not await is_owner_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Owner access required.", show_alert=True); return
    await state.set_state("community_welcome_button")
    await state.update_data(community_id=callback_data.community_id)
    await call.message.answer("🔘 Send the new welcome-button text (max 64 characters).")
    await call.answer()


@router.message(StateFilter("community_welcome_button"))
async def ui_welcome_button_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data(); community_id = data.get("community_id")
    if not community_id or not await is_owner_of_community(message.from_user.id, community_id, session):
        await state.clear(); return
    text = (message.text or "").strip()[:64]
    if not text:
        await message.answer("Please send button text."); return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await state.clear(); await message.answer("Community not found."); return
    community.welcome_button_text = text
    await session.flush(); await state.clear()
    await message.answer("✅ Welcome button updated.", reply_markup=community_settings_keyboard(community_id))


@router.callback_query(AdminCB.filter(F.action == "welcome_media"))
async def ui_welcome_media(call, callback_data: AdminCB, session: AsyncSession, state: FSMContext) -> None:
    if not await is_owner_of_community(call.from_user.id, callback_data.community_id, session):
        await call.answer("Owner access required.", show_alert=True); return
    await state.set_state("community_welcome_media")
    await state.update_data(community_id=callback_data.community_id)
    await call.message.answer("🖼 Send the new welcome photo, video, GIF, or sticker.\nSend /skip to remove the current media.")
    await call.answer()


@router.message(StateFilter("community_welcome_media"))
async def ui_welcome_media_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data(); community_id = data.get("community_id")
    if not community_id or not await is_owner_of_community(message.from_user.id, community_id, session):
        await state.clear(); return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await state.clear(); await message.answer("Community not found."); return
    if (message.text or "").strip().lower() == "/skip":
        from app.database.models import MediaType
        community.welcome_media_type = MediaType.NONE
        community.welcome_media_file_id = None
    elif message.photo:
        from app.database.models import MediaType
        community.welcome_media_type = MediaType.PHOTO; community.welcome_media_file_id = message.photo[-1].file_id
    elif message.video:
        from app.database.models import MediaType
        community.welcome_media_type = MediaType.VIDEO; community.welcome_media_file_id = message.video.file_id
    elif message.animation:
        from app.database.models import MediaType
        community.welcome_media_type = MediaType.ANIMATION; community.welcome_media_file_id = message.animation.file_id
    elif message.sticker:
        from app.database.models import MediaType
        community.welcome_media_type = MediaType.STICKER; community.welcome_media_file_id = message.sticker.file_id
    else:
        await message.answer("Send a supported media item or /skip."); return
    await session.flush(); await state.clear()
    await message.answer("✅ Welcome media updated.", reply_markup=community_settings_keyboard(community_id))


@router.message(StateFilter("admin_referral_target"))
async def ui_referral_target_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data(); community_id = data.get("admin_community_id")
    if not community_id or not await is_owner_of_community(message.from_user.id, community_id, session):
        await state.clear(); return
    text = (message.text or "").strip()
    if not text.isdigit() or not 1 <= int(text) <= 10:
        await message.answer("Send a number from 1 to 10."); return
    community = await community_service.get_by_id(session, community_id)
    if community is None:
        await state.clear(); await message.answer("Community not found."); return
    community.referral_target = int(text)
    await session.flush(); await state.clear()
    await message.answer(f"✅ Access requirement set to <b>{text}</b> successful referrals.", reply_markup=referral_settings_keyboard(community_id))
