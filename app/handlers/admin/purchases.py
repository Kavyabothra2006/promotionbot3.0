from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Community, PurchaseRequest, PurchaseRequestStatus, User, UnlockMethod
from app.filters.admin_filter import IsAdminFilter, is_admin_of_community
from app.keyboards.callback_data import PurchaseCB
from app.services import admin_service, premium_service

router = Router(name="admin_purchases")
router.callback_query.filter(IsAdminFilter())


@router.callback_query(F.data.startswith("pur:"))
async def purchase_action(call: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    parts = (call.data or "").split(":")
    if len(parts) != 4:
        await call.answer("Invalid purchase action.", show_alert=True)
        return
    _, action, community_raw, request_raw = parts
    if action not in {"approve", "reject"} or not community_raw.isdigit() or not request_raw.isdigit():
        await call.answer("Invalid purchase action.", show_alert=True)
        return
    community_id, request_id = int(community_raw), int(request_raw)
    if not await is_admin_of_community(call.from_user.id, community_id, session):
        await call.answer("Not authorized for this community.", show_alert=True)
        return

    result = await session.execute(
        select(PurchaseRequest, User)
        .join(User, User.id == PurchaseRequest.user_id)
        .where(
            PurchaseRequest.id == request_id,
            PurchaseRequest.community_id == community_id,
            PurchaseRequest.status == PurchaseRequestStatus.PENDING,
        )
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await call.answer("This purchase request is no longer pending.", show_alert=True)
        return
    request, user = row

    if action == "reject":
        request.status = PurchaseRequestStatus.REJECTED
        await session.commit()
        try:
            await bot.send_message(user.telegram_id, "❌ Your Premium purchase request was rejected. Please contact an admin.")
        except TelegramAPIError:
            pass
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer("Purchase request rejected.")
        return

    if user.is_banned:
        request.status = PurchaseRequestStatus.REJECTED
        await session.commit()
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer("Banned users cannot be granted Premium.", show_alert=True)
        return
    if user.is_premium:
        request.status = PurchaseRequestStatus.COMPLETED
        await session.commit()
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer("User is already Premium.")
        return

    community = await session.get(Community, community_id)
    if community is None or not community.is_active:
        await call.answer("Community not found or inactive.", show_alert=True)
        return

    invite = await premium_service.unlock_premium(bot, session, community, user, UnlockMethod.MANUAL)
    if invite is None:
        await call.answer("Premium unlock could not be completed. Request remains pending.", show_alert=True)
        return

    request.status = PurchaseRequestStatus.COMPLETED
    await session.commit()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Premium approved and invite generated.")
