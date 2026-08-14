from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.models import Community
from app.keyboards.callback_data import AdminCB

PAGE_SIZE = 8


def admin_root_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👥 Communities", callback_data=AdminCB(action="communities"))
    b.button(text="👤 Users", callback_data=AdminCB(action="users"))
    b.button(text="📢 Broadcast", callback_data=AdminCB(action="broadcast"))
    b.button(text="💳 Payments", callback_data=AdminCB(action="payments"))
    b.button(text="📈 Analytics", callback_data=AdminCB(action="analytics"))
    b.button(text="👮 Admin Management", callback_data=AdminCB(action="admins"))
    b.button(text="💾 Backup & Export", callback_data=AdminCB(action="backup"))
    b.button(text="⚙️ Global Settings", callback_data=AdminCB(action="global_settings"))
    b.adjust(2, 2, 2, 2)
    return b.as_markup()


def community_picker_keyboard(communities: list[Community], page: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    total_pages = max(1, (len(communities) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = communities[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    for c in chunk:
        b.button(text=f"📋 {c.name[:58]}", callback_data=AdminCB(action="community", community_id=c.id, page=page))
    b.button(text="➕ Add Community", callback_data=AdminCB(action="add_community"))
    if page > 0:
        b.button(text="◀ Previous", callback_data=AdminCB(action="communities", page=page - 1))
    if page + 1 < total_pages:
        b.button(text="Next ▶", callback_data=AdminCB(action="communities", page=page + 1))
    b.button(text="⬅️ Admin Panel", callback_data=AdminCB(action="root"))
    b.adjust(1)
    return b.as_markup()


def community_menu_keyboard(community_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📋 Community Info", callback_data=AdminCB(action="community_info", community_id=community_id))
    b.button(text="⚙️ Community Settings", callback_data=AdminCB(action="community_settings", community_id=community_id))
    b.button(text="⚠️ Danger Zone", callback_data=AdminCB(action="danger", community_id=community_id))
    b.button(text="⬅️ Connected Communities", callback_data=AdminCB(action="communities"))
    b.adjust(1)
    return b.as_markup()


def community_settings_keyboard(community_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👋 Welcome Message", callback_data=AdminCB(action="welcome_text", community_id=community_id))
    b.button(text="🔘 Welcome Button", callback_data=AdminCB(action="welcome_button", community_id=community_id))
    b.button(text="🖼 Welcome Media", callback_data=AdminCB(action="welcome_media", community_id=community_id))
    b.button(text="🎁 Referral Settings", callback_data=AdminCB(action="referral_settings", community_id=community_id))
    b.button(text="🧹 Join/Leave Cleanup", callback_data=AdminCB(action="cleanup", community_id=community_id))
    b.button(text="🚪 Remove on Leave", callback_data=AdminCB(action="remove_on_leave", community_id=community_id))
    b.button(text="⬅️ Community", callback_data=AdminCB(action="community", community_id=community_id))
    b.adjust(1)
    return b.as_markup()


def cleanup_keyboard(community_id: int, current: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    labels = [("daily", "🗓 Every Day"), ("3days", "📅 Every 3 Days"), ("weekly", "📆 Every Week"), ("now", "🗑 Clean Now"), ("disabled", "❌ Disable")]
    for value, label in labels:
        marker = " ✅" if current == value else ""
        b.button(text=label + marker, callback_data=AdminCB(action="cleanup_set", community_id=community_id, value=value))
    b.button(text="⬅️ Community Settings", callback_data=AdminCB(action="community_settings", community_id=community_id))
    b.adjust(1)
    return b.as_markup()


def referral_settings_keyboard(community_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎯 Change Required Referrals", callback_data=AdminCB(action="referral_target", community_id=community_id))
    b.button(text="⬅️ Community Settings", callback_data=AdminCB(action="community_settings", community_id=community_id))
    b.adjust(1)
    return b.as_markup()


def danger_keyboard(community_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⚠️ Deactivate Community", callback_data=AdminCB(action="deactivate", community_id=community_id))
    b.button(text="⬅️ Community", callback_data=AdminCB(action="community", community_id=community_id))
    b.adjust(1)
    return b.as_markup()


def confirm_deactivate_keyboard(community_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❌ Cancel", callback_data=AdminCB(action="danger", community_id=community_id))
    b.button(text="⚠️ Confirm", callback_data=AdminCB(action="deactivate_confirm", community_id=community_id, value="yes"))
    b.adjust(2)
    return b.as_markup()


def admin_panel_keyboard(community_id: int) -> InlineKeyboardMarkup:
    # Compatibility for existing callers: selecting a community now opens its submenu.
    return community_menu_keyboard(community_id)


def purchase_request_keyboard(community_id: int, request_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Approve", callback_data=f"pur:approve:{community_id}:{request_id}")
    b.button(text="❌ Reject", callback_data=f"pur:reject:{community_id}:{request_id}")
    b.adjust(2)
    return b.as_markup()
