from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)


class ThrottlingMiddleware(BaseMiddleware):
    """Throttle user-generated interaction without ever dropping membership state events."""

    def __init__(self, redis: Redis, rate_limit: float | None = None) -> None:
        self.redis = redis
        self.rate_limit = rate_limit if rate_limit is not None else settings.THROTTLE_RATE_LIMIT

    @staticmethod
    def _user_and_kind(event: TelegramObject):
        if not isinstance(event, Update):
            return None, None
        if event.chat_member is not None:
            return event.chat_member.from_user, "chat_member"
        if event.chat_join_request is not None:
            return event.chat_join_request.from_user, "chat_join_request"
        if event.message is not None:
            return event.message.from_user, "message"
        if event.callback_query is not None:
            return event.callback_query.from_user, "callback_query"
        if event.inline_query is not None:
            return event.inline_query.from_user, "inline_query"
        if event.my_chat_member is not None:
            return event.my_chat_member.from_user, "my_chat_member"
        return None, None

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user, event_kind = self._user_and_kind(event)

        # Membership transitions are authoritative business events. Never discard them.
        if user is None or event_kind in {"chat_member", "chat_join_request", "my_chat_member"}:
            return await handler(event, data)

        chat_id = None
        if isinstance(event, Update):
            if event.message:
                chat_id = event.message.chat.id
            elif event.callback_query and event.callback_query.message:
                chat_id = event.callback_query.message.chat.id

        key = f"throttle:{event_kind}:{chat_id or 'dm'}:{user.id}"
        acquired = await self.redis.set(
            key,
            "1",
            px=max(1, int(self.rate_limit * 1000)),
            nx=True,
        )
        if not acquired:
            logger.debug("Throttled user=%s event=%s", user.id, event_kind)
            return None
        return await handler(event, data)
