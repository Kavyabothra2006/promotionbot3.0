from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ProcessedUpdate

logger = logging.getLogger(__name__)


class UpdateIdempotencyMiddleware(BaseMiddleware):
    """Serialize duplicate update deliveries and persist completion only after success."""

    def __init__(self, redis: Redis, lock_timeout: int = 300) -> None:
        self.redis = redis
        self.lock_timeout = lock_timeout

    async def _heartbeat(self, lock) -> None:
        interval = max(30, self.lock_timeout // 3)
        while True:
            await asyncio.sleep(interval)
            await lock.extend(self.lock_timeout)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)
        session: AsyncSession | None = data.get("session")
        if session is None:
            return await handler(event, data)

        update_id = event.update_id
        exists = await session.execute(
            select(ProcessedUpdate.id).where(ProcessedUpdate.update_id == update_id).limit(1)
        )
        if exists.scalar_one_or_none() is not None:
            logger.debug("Skipping already-completed Telegram update_id=%s", update_id)
            return None

        lock = self.redis.lock(f"telegram:update:{update_id}", timeout=self.lock_timeout, blocking=False)
        acquired = await lock.acquire()
        if not acquired:
            logger.warning("Skipping concurrently processing Telegram update_id=%s", update_id)
            return None

        heartbeat = asyncio.create_task(self._heartbeat(lock), name=f"telegram-update-heartbeat-{update_id}")
        try:
            exists = await session.execute(
                select(ProcessedUpdate.id).where(ProcessedUpdate.update_id == update_id).limit(1)
            )
            if exists.scalar_one_or_none() is not None:
                return None

            result = await handler(event, data)
            session.add(ProcessedUpdate(update_id=update_id))
            await session.flush()
            return result
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            try:
                await lock.release()
            except Exception:
                logger.warning("Could not release Telegram update lock update_id=%s", update_id)
