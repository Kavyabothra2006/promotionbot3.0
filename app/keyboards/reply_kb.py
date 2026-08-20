from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def user_main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Referral"), KeyboardButton(text="❓ Help")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose an option",
    )


def admin_main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Communities"), KeyboardButton(text="👤 Users")],
            [KeyboardButton(text="📢 Broadcast"), KeyboardButton(text="💳 Payments")],
            [KeyboardButton(text="📈 Analytics"), KeyboardButton(text="👮 Admin Management")],
            [KeyboardButton(text="💾 Backup & Export"), KeyboardButton(text="⚙️ Global Settings")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Admin panel",
    )
