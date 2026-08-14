from __future__ import annotations

import asyncio
import logging
import re
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import async_session_factory
from app.database.models import (
    BroadcastContentType,
    BroadcastDelivery,
    BroadcastDeliveryStatus,
    BroadcastLog,
    BroadcastScope,
    BroadcastStatus,
    User,
)
from app.filters.admin_filter import IsAdminFilter, is_admin_of_community
from app.services import community_service

router = Router(name="admin_broadcast")
router.message.filter(IsAdminFilter())
logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task] = set()
_broadcast_redis: Redis | None = None
_BUTTON_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)\s*$")
LEASE_SECONDS = 600
STALE_SECONDS = 600
RECOVERY_INTERVAL_SECONDS = 60
LOCK_HEARTBEAT_SECONDS = 60


class Broadcast(StatesGroup):
    waiting_content = State()


def configure_broadcast_redis(redis: Redis) -> None:
    global _broadcast_redis
    _broadcast_redis = redis


def _extract_button(text: str) -> tuple[str, InlineKeyboardMarkup | None]:
    match = _BUTTON_PATTERN.search(text.strip())
    if not match:
        return text, None
    clean_text = text[: match.start()].strip()
    builder = InlineKeyboardBuilder()
    builder.button(text=match.group(1)[:64], url=match.group(2))
    return clean_text, builder.as_markup()


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject, state: FSMContext, session: AsyncSession) -> None:
    args = (command.args or "").split()
    if len(args) != 2 or not args[0].isdigit() or args[1] not in ("all", "premium", "premium_only"):
        await message.answer("Usage: /broadcast <community_id> <all|premium>\nThen send the content in your next message.")
        return
    community_id = int(args[0])
    if not await is_admin_of_community(message.from_user.id, community_id, session):
        await message.answer("Not authorized for this community.")
        return
    await state.update_data(community_id=community_id, scope=("premium_only" if args[1] in ("premium", "premium_only") else "all"))
    await state.set_state(Broadcast.waiting_content)
    await message.answer("Send text, photo, video, GIF, or sticker. Append one URL button as [Text](https://example.com) if needed.")


async def _send_one(bot: Bot, telegram_id: int, content_type: BroadcastContentType, content_file_id: str | None, content_text: str | None, reply_markup: InlineKeyboardMarkup | None) -> None:
    if content_type == BroadcastContentType.TEXT:
        await bot.send_message(telegram_id, content_text or "", reply_markup=reply_markup)
    elif content_type == BroadcastContentType.PHOTO:
        await bot.send_photo(telegram_id, content_file_id, caption=content_text, reply_markup=reply_markup)
    elif content_type == BroadcastContentType.VIDEO:
        await bot.send_video(telegram_id, content_file_id, caption=content_text, reply_markup=reply_markup)
    elif content_type == BroadcastContentType.ANIMATION:
        await bot.send_animation(telegram_id, content_file_id, caption=content_text, reply_markup=reply_markup)
    elif content_type == BroadcastContentType.STICKER:
        await bot.send_sticker(telegram_id, content_file_id)


async def _renew_broadcast_lease(lock, job_id: int, worker_token: str) -> None:
    while True:
        await asyncio.sleep(LOCK_HEARTBEAT_SECONDS)
        try:
            await lock.extend(LEASE_SECONDS)
            async with async_session_factory() as session:
                job = await session.get(BroadcastLog, job_id)
                if job is None or job.status != BroadcastStatus.RUNNING or job.worker_token != worker_token:
                    raise RuntimeError(f"Broadcast worker ownership lost for job={job_id}")
                job.started_at = datetime.now(timezone.utc)
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Broadcast lease heartbeat failed job=%s", job_id)
            raise


async def _run_broadcast(bot: Bot, job_id: int) -> None:
    if _broadcast_redis is None:
        raise RuntimeError("Broadcast Redis lock is not configured")
    lock = _broadcast_redis.lock(f"broadcast:job:{job_id}", timeout=LEASE_SECONDS, blocking=False)
    try:
        acquired = await lock.acquire()
    except Exception:
        logger.exception("Could not acquire broadcast lock job=%s", job_id)
        return
    if not acquired:
        return

    heartbeat_task: asyncio.Task | None = None
    worker_token = uuid4().hex
    try:
        async with async_session_factory() as session:
            job = await session.get(BroadcastLog, job_id)
            if job is None or job.status == BroadcastStatus.COMPLETED:
                return
            job.status = BroadcastStatus.RUNNING
            job.worker_token = worker_token
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

        heartbeat_task = asyncio.create_task(_renew_broadcast_lease(lock, job_id, worker_token), name=f"broadcast-heartbeat-{job_id}")

        async with async_session_factory() as session:
            job = await session.get(BroadcastLog, job_id)
            if job is None or job.status == BroadcastStatus.COMPLETED:
                return
            reply_markup = None
            clean_text = job.content_text
            if clean_text:
                clean_text, reply_markup = _extract_button(clean_text)

            sent = job.sent_count or 0
            failed = job.failed_count or 0
            while True:
                if heartbeat_task.done():
                    heartbeat_task.result()
                owner = await session.execute(select(BroadcastLog.worker_token, BroadcastLog.status).where(BroadcastLog.id == job_id))
                owner_row = owner.first()
                if owner_row is None or owner_row[0] != worker_token or owner_row[1] != BroadcastStatus.RUNNING:
                    logger.warning("Broadcast worker ownership lost; stopping job=%s", job_id)
                    return

                delivery = (
                    await session.execute(
                        select(BroadcastDelivery)
                        .where(
                            BroadcastDelivery.broadcast_id == job_id,
                            BroadcastDelivery.status == BroadcastDeliveryStatus.PENDING,
                        )
                        .order_by(BroadcastDelivery.telegram_id.asc())
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                ).scalar_one_or_none()
                if delivery is None:
                    break

                delivery.attempts += 1
                await session.commit()
                delivered = False
                last_error = None
                for _attempt in range(3):
                    try:
                        await _send_one(bot, delivery.telegram_id, job.content_type, job.content_file_id, clean_text, reply_markup)
                        delivered = True
                        break
                    except TelegramRetryAfter as exc:
                        last_error = str(exc)
                        remaining = float(exc.retry_after)
                        while remaining > 0:
                            await asyncio.sleep(min(30.0, remaining))
                            remaining -= 30.0
                            if heartbeat_task.done():
                                heartbeat_task.result()
                    except TelegramAPIError as exc:
                        last_error = str(exc)
                        break

                if delivered:
                    delivery.status = BroadcastDeliveryStatus.SENT
                    delivery.sent_at = datetime.now(timezone.utc)
                    sent += 1
                else:
                    delivery.status = BroadcastDeliveryStatus.FAILED
                    delivery.last_error = last_error[:2000] if last_error else "unknown error"
                    failed += 1
                job.sent_count = sent
                job.failed_count = failed
                job.last_processed_telegram_id = delivery.telegram_id
                job.started_at = datetime.now(timezone.utc)
                await session.commit()
                await asyncio.sleep(0.05)

            owner = await session.execute(select(BroadcastLog.worker_token, BroadcastLog.status).where(BroadcastLog.id == job_id))
            owner_row = owner.first()
            if owner_row is None or owner_row[0] != worker_token or owner_row[1] != BroadcastStatus.RUNNING:
                return
            job.status = BroadcastStatus.COMPLETED
            job.worker_token = None
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Broadcast %s crashed; durable delivery rows remain for recovery", job_id)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        try:
            await lock.release()
        except Exception:
            pass


@router.message(StateFilter(Broadcast.waiting_content))
async def receive_broadcast_content(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    community_id = int(data["community_id"])
    scope = str(data["scope"])
    if scope == "premium":
        scope = "premium_only"
    if not await is_admin_of_community(message.from_user.id, community_id, session):
        await state.clear()
        await message.answer("Not authorized for this community.")
        return
    community = await community_service.get_by_id(session, community_id)
    if community is None or not community.is_active:
        await state.clear()
        await message.answer("Community not found or inactive.")
        return

    content_type: BroadcastContentType
    content_file_id: str | None = None
    content_text: str | None = None
    if message.text:
        content_type, content_text = BroadcastContentType.TEXT, message.text
    elif message.photo:
        content_type, content_file_id, content_text = BroadcastContentType.PHOTO, message.photo[-1].file_id, message.caption
    elif message.video:
        content_type, content_file_id, content_text = BroadcastContentType.VIDEO, message.video.file_id, message.caption
    elif message.animation:
        content_type, content_file_id, content_text = BroadcastContentType.ANIMATION, message.animation.file_id, message.caption
    elif message.sticker:
        content_type, content_file_id = BroadcastContentType.STICKER, message.sticker.file_id
    else:
        await message.answer("Unsupported content. Send text, photo, video, animation, or sticker.")
        return

    filters = [User.community_id == community_id, User.is_banned.is_(False)]
    if scope == "premium":
        filters.append(User.is_premium.is_(True))
    result = await session.execute(select(User.telegram_id).where(*filters).order_by(User.telegram_id.asc()))
    recipient_ids = sorted(set(result.scalars().all()))

    job = BroadcastLog(
        community_id=community_id,
        admin_telegram_id=message.from_user.id,
        scope=BroadcastScope(scope),
        content_type=content_type,
        content_file_id=content_file_id,
        content_text=content_text,
        total_count=len(recipient_ids),
        status=BroadcastStatus.PENDING,
    )
    session.add(job)
    await session.flush()
    for telegram_id in recipient_ids:
        session.add(BroadcastDelivery(broadcast_id=job.id, telegram_id=telegram_id))
    await session.commit()
    await state.clear()

    task = asyncio.create_task(_run_broadcast(message.bot, job.id), name=f"broadcast-{job.id}")
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    await message.answer(f"📨 Broadcast #{job.id} queued for {len(recipient_ids)} recipients.")


async def recover_broadcast_jobs(bot: Bot) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_SECONDS)
    async with async_session_factory() as session:
        result = await session.execute(
            select(BroadcastLog).where(
                (BroadcastLog.status == BroadcastStatus.PENDING)
                | ((BroadcastLog.status == BroadcastStatus.RUNNING) & (BroadcastLog.started_at < cutoff))
            ).order_by(BroadcastLog.id.asc())
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            if job.status == BroadcastStatus.RUNNING:
                job.status = BroadcastStatus.PENDING
                job.worker_token = None
                job.finished_at = None
        if jobs:
            await session.commit()
    for job in jobs:
        task = asyncio.create_task(_run_broadcast(bot, job.id), name=f"broadcast-{job.id}")
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def broadcast_recovery_loop(bot: Bot) -> None:
    while True:
        try:
            await recover_broadcast_jobs(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Broadcast recovery loop failed")
        await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)


async def shutdown_broadcast_tasks() -> None:
    tasks = list(_background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _background_tasks.clear()
