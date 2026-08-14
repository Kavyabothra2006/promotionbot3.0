from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import Community
from app.keyboards.callback_data import AdminCB

PAGE_SIZE = 8


def community_picker_keyboard(communities: list[Community], page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total_pages = max(1, (len(communities) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = communities[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    for c in chunk:
        builder.button(
            text=f"🏠 {c.name[:58]}",
            callback_data=AdminCB(action="panel", community_id=c.id, page=page),
        )
    builder.adjust(1)

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="◀️ Previous",
                callback_data=AdminCB(action="communities", community_id=0, page=page - 1).pack(),
            )
        )
    if page + 1 < total_pages:
        nav.append(
            InlineKeyboardButton(
                text="Next ▶️",
                callback_data=AdminCB(action="communities", community_id=0, page=page + 1).pack(),
            )
        )
    if nav:
        builder.row(*nav)

    return builder.as_markup()


def admin_panel_keyboard(community_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Analytics", callback_data=AdminCB(action="analytics", community_id=community_id))
    builder.button(text="⚙️ Settings", callback_data=AdminCB(action="settings", community_id=community_id))
    builder.button(text="🔄 Refresh", callback_data=AdminCB(action="panel", community_id=community_id))
    builder.button(
        text="🏠 All Communities",
        callback_data=AdminCB(action="communities", community_id=0, page=0),
    )
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def purchase_request_keyboard(community_id: int, request_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Approve", callback_data=f"pur:approve:{community_id}:{request_id}")
    builder.button(text="❌ Reject", callback_data=f"pur:reject:{community_id}:{request_id}")
    builder.adjust(2)
    return builder.as_markup()
