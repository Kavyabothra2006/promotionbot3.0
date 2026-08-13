from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.database.base import get_session


class DbSessionMiddleware(BaseMiddleware):
    """Opens one AsyncSession per update and injects it as `session` into handler kwargs.
    Commits on success, rolls back on any exception (see get_session)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with get_session() as session:
            data["session"] = session
            return await handler(event, data)
