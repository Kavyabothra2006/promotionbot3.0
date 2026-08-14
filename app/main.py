from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from app.config import settings
from app.core.logging import setup_logging
from app.database.base import check_database, dispose_engine, get_session
from app.handlers.admin import backup as backup_handlers
from app.handlers.admin import admins as admins_handlers
from app.handlers.admin import broadcast as broadcast_handlers
from app.handlers.admin import onboarding as onboarding_handlers
from app.handlers.admin import panel as panel_handlers
from app.handlers.admin import purchases as purchases_handlers
from app.handlers.admin import settings as settings_handlers
from app.handlers.group import cleaner as cleaner_handlers
from app.handlers.group import premium_membership as premium_membership_handlers
from app.handlers.group import welcome as welcome_handlers
from app.handlers.user import dashboard as dashboard_handlers
from app.handlers.user import start as start_handlers
from app.handlers.user import verification as verification_handlers
from app.middlewares.db_session import DbSessionMiddleware
from app.middlewares.throttling import ThrottlingMiddleware
from app.middlewares.idempotency import UpdateIdempotencyMiddleware
from app.services.premium_service import expire_stale_invites, retry_pending_referral_unlocks
from app.database.models import ProcessedUpdate
from sqlalchemy import delete
from datetime import datetime, timedelta, timezone
from app.services.membership_reconcile import membership_reconcile_loop
from app.core.error_handler import on_error
from app.core.command_menu import configure_command_menus

logger = logging.getLogger(__name__)
INVITE_EXPIRY_CHECK_INTERVAL_SECONDS = 900
PROCESSED_UPDATE_CLEANUP_INTERVAL_SECONDS = 86400


async def _referral_unlock_retry_loop(bot: Bot) -> None:
    while True:
        try:
            unlocked = await retry_pending_referral_unlocks(bot)
            if unlocked:
                logger.info("Retried %d pending referral Premium unlock(s)", unlocked)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Referral Premium unlock retry job failed")
        await asyncio.sleep(60)


async def _invite_expiry_loop(bot: Bot) -> None:
    while True:
        try:
            async with get_session() as session:
                revoked = await expire_stale_invites(bot, session)
                if revoked:
                    logger.info("Revoked %d stale premium invite(s)", revoked)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Invite expiry background job failed")
        await asyncio.sleep(INVITE_EXPIRY_CHECK_INTERVAL_SECONDS)


async def _processed_update_cleanup_loop() -> None:
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=settings.PROCESSED_UPDATE_RETENTION_DAYS)
            async with get_session() as session:
                result = await session.execute(delete(ProcessedUpdate).where(ProcessedUpdate.processed_at < cutoff))
                if result.rowcount:
                    logger.info("Deleted %d expired processed Telegram update records", result.rowcount)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Processed update cleanup failed")
        await asyncio.sleep(PROCESSED_UPDATE_CLEANUP_INTERVAL_SECONDS)


def _register_routers(dp: Dispatcher) -> None:
    dp.include_router(onboarding_handlers.router)
    dp.include_router(panel_handlers.router)
    dp.include_router(purchases_handlers.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(broadcast_handlers.router)
    dp.include_router(backup_handlers.router)
    dp.include_router(admins_handlers.router)
    dp.include_router(dashboard_handlers.router)
    dp.include_router(start_handlers.router)
    dp.include_router(verification_handlers.router)
    dp.include_router(welcome_handlers.router)
    dp.include_router(premium_membership_handlers.router)
    dp.include_router(cleaner_handlers.router)


async def main() -> None:
    setup_logging()
    logger.info("Starting bot | environment=%s", settings.ENVIRONMENT)

    await check_database()
    redis = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
    )
    await redis.ping()

    storage = RedisStorage(redis=redis)
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=storage)
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(UpdateIdempotencyMiddleware(redis=redis, lock_timeout=settings.IDEMPOTENCY_LOCK_SECONDS))
    dp.update.middleware(ThrottlingMiddleware(redis=redis))
    dp.errors.register(on_error)
    async with get_session() as command_session:
        await configure_command_menus(bot, command_session)
        await command_session.commit()
    _register_routers(dp)
    broadcast_handlers.configure_broadcast_redis(redis)

    expiry_task = asyncio.create_task(_invite_expiry_loop(bot), name="invite-expiry")
    referral_retry_task = asyncio.create_task(_referral_unlock_retry_loop(bot), name="referral-unlock-retry")
    await broadcast_handlers.recover_broadcast_jobs(bot)
    broadcast_recovery_task = asyncio.create_task(
        broadcast_handlers.broadcast_recovery_loop(bot), name="broadcast-recovery"
    )
    processed_update_cleanup_task = asyncio.create_task(_processed_update_cleanup_loop(), name="processed-update-cleanup")
    membership_reconcile_task = asyncio.create_task(
        membership_reconcile_loop(bot), name="membership-reconcile"
    )

    try:
        # Preserve pending Telegram updates across restarts. Missing chat_member/join-request
        # events can corrupt referral and Premium state.
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "chat_member", "chat_join_request", "my_chat_member"],
        )
    finally:
        expiry_task.cancel()
        referral_retry_task.cancel()
        broadcast_recovery_task.cancel()
        processed_update_cleanup_task.cancel()
        membership_reconcile_task.cancel()
        try:
            await expiry_task
        except asyncio.CancelledError:
            pass
        try:
            await referral_retry_task
        except asyncio.CancelledError:
            pass
        try:
            await broadcast_recovery_task
        except asyncio.CancelledError:
            pass
        try:
            await processed_update_cleanup_task
        except asyncio.CancelledError:
            pass
        try:
            await membership_reconcile_task
        except asyncio.CancelledError:
            pass
        await broadcast_handlers.shutdown_broadcast_tasks()
        await bot.session.close()
        await storage.close()
        await redis.aclose()
        await dispose_engine()


if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main())
