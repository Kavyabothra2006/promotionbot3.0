from __future__ import annotations

from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.keyboards.callback_data import MenuCB, ReferralCB, PurchaseCB


def user_main_keyboard(community_id: int) -> InlineKeyboardMarkup:
    """Primary user navigation. Every button maps to an existing bot capability."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📤 Refer & Unlock",
        callback_data=MenuCB(action="choose_referral", community_id=community_id),
    )
    builder.button(
        text="💎 Instant Access",
        callback_data=MenuCB(action="choose_instant", community_id=community_id),
    )
    builder.button(
        text="📊 My Dashboard",
        callback_data=MenuCB(action="dashboard", community_id=community_id),
    )
    builder.button(
        text="🔗 My Referral Link",
        callback_data=ReferralCB(action="get_link", community_id=community_id),
    )
    builder.button(
        text="🔄 Refresh",
        callback_data=MenuCB(action="back_main", community_id=community_id),
    )
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def welcome_keyboard(button_text: str, bot_username: str, community_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=button_text,
        url=f"https://t.me/{bot_username}?start=verify_{community_id}",
    )
    builder.adjust(1)
    return builder.as_markup()


def verification_menu_keyboard(completed: int, target: int, community_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"📤 Refer & Unlock  •  {completed}/{target}",
        callback_data=MenuCB(action="choose_referral", community_id=community_id),
    )
    builder.button(
        text="💎 Get Instant Access",
        callback_data=MenuCB(action="choose_instant", community_id=community_id),
    )
    builder.button(
        text="📊 My Dashboard",
        callback_data=MenuCB(action="dashboard", community_id=community_id),
    )
    builder.button(
        text="🔗 My Referral Link",
        callback_data=ReferralCB(action="get_link", community_id=community_id),
    )
    builder.button(
        text="🔄 Refresh",
        callback_data=MenuCB(action="back_main", community_id=community_id),
    )
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def referral_menu_keyboard(community_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔗 Get My Invite Link",
        callback_data=ReferralCB(action="get_link", community_id=community_id),
    )
    builder.button(
        text="🔄 Check Progress",
        callback_data=ReferralCB(action="check_progress", community_id=community_id),
    )
    builder.button(
        text="💎 Instant Access",
        callback_data=MenuCB(action="choose_instant", community_id=community_id),
    )
    builder.button(
        text="⬅️ Back to Main Menu",
        callback_data=MenuCB(action="back_main", community_id=community_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def referral_link_keyboard(referral_link: str, community_id: int) -> InlineKeyboardMarkup:
    share_text = quote("Join this awesome community and unlock Premium with me! 🚀")
    share_url = f"https://t.me/share/url?url={quote(referral_link, safe='')}&text={share_text}"
    builder = InlineKeyboardBuilder()
    builder.button(text="📤 Share Invite Link", url=share_url)
    builder.button(
        text="🔄 Check Progress",
        callback_data=ReferralCB(action="check_progress", community_id=community_id),
    )
    builder.button(
        text="💎 Instant Access",
        callback_data=MenuCB(action="choose_instant", community_id=community_id),
    )
    builder.button(
        text="⬅️ Back to Main Menu",
        callback_data=MenuCB(action="back_main", community_id=community_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def instant_access_keyboard(admin_url: str, community_id: int, request_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📨 Contact Admin", url=admin_url)
    builder.button(
        text="✅ I Sent the Request",
        callback_data=PurchaseCB(action="sent", community_id=community_id, request_id=request_id),
    )
    builder.button(
        text="⬅️ Back to Main Menu",
        callback_data=MenuCB(action="back_main", community_id=community_id),
    )
    builder.adjust(1)
    return builder.as_markup()


def dashboard_keyboard(community_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📤 Refer & Unlock",
        callback_data=MenuCB(action="choose_referral", community_id=community_id),
    )
    builder.button(
        text="💎 Instant Access",
        callback_data=MenuCB(action="choose_instant", community_id=community_id),
    )
    builder.button(
        text="🔗 My Referral Link",
        callback_data=ReferralCB(action="get_link", community_id=community_id),
    )
    builder.button(
        text="⬅️ Back to Main Menu",
        callback_data=MenuCB(action="back_main", community_id=community_id),
    )
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def join_premium_keyboard(invite_link: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔓 Join Premium", url=invite_link)
    builder.adjust(1)
    return builder.as_markup()
