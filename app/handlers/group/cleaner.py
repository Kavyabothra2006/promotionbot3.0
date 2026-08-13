from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Community
from app.services import community_service

logger = logging.getLogger(__name__)
router = Router(name="group_cleaner")


async def _managed_community(session: AsyncSession, chat_id: int) -> Community | None:
    return await community_service.get_by_verification_chat(session, chat_id) or await community_service.get_by_premium_chat(
        session, chat_id
    )


@router.message(F.new_chat_members)
async def clean_join_message(message: Message, session: AsyncSession, bot: Bot) -> None:
    community = await _managed_community(session, message.chat.id)
    if community is None or not community.delete_join_leave_messages:
        return
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except TelegramAPIError:
        pass


@router.message(F.left_chat_member)
async def clean_leave_message(message: Message, session: AsyncSession, bot: Bot) -> None:
    community = await _managed_community(session, message.chat.id)
    if community is None or not community.delete_join_leave_messages:
        return
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except TelegramAPIError:
        pass
