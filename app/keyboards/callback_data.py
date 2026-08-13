from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="menu"):
    action: str
    community_id: int


class ReferralCB(CallbackData, prefix="ref"):
    action: str
    community_id: int


class PurchaseCB(CallbackData, prefix="pur"):
    action: str
    community_id: int
    request_id: int


class AdminCB(CallbackData, prefix="adm"):
    action: str
    community_id: int
    page: int = 0


class ConfirmCB(CallbackData, prefix="cfm"):
    action: str
    community_id: int
    yes: bool
