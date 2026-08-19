from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Community, PendingReferral, ReferralStatus, User
from app.utils.referral_code import generate_referral_code

logger = logging.getLogger(__name__)


async def _unique_referral_code(session: AsyncSession) -> str:
    for _ in range(10):
        code = generate_referral_code()
        if (await session.execute(select(User.id).where(User.referral_code == code))).scalar_one_or_none() is None:
            return code
    raise RuntimeError("Could not generate a unique referral code")


async def get_or_create_user(session: AsyncSession, community_id: int, telegram_id: int, username: str | None, first_name: str | None) -> User:
    result = await session.execute(select(User).where(User.community_id == community_id, User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user is not None:
        if username != user.username:
            user.username = username
        if first_name and first_name != user.first_name:
            user.first_name = first_name
        return user

    for _ in range(5):
        user = User(
            community_id=community_id,
            telegram_id=telegram_id,
            username=username,
            first_name=first_name or "",
            referral_code=await _unique_referral_code(session),
        )
        try:
            async with session.begin_nested():
                session.add(user)
                await session.flush()
            return user
        except IntegrityError:
            existing = (
                await session.execute(
                    select(User).where(User.community_id == community_id, User.telegram_id == telegram_id)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing
    raise RuntimeError("Could not create user after concurrent retries")


async def build_referral_link(bot_username: str, referral_code: str) -> str:
    return f"https://t.me/{bot_username}?start={referral_code}"


async def resolve_community_by_referral_code(session: AsyncSession, code: str) -> Community | None:
    result = await session.execute(
        select(Community)
        .join(User, User.community_id == Community.id)
        .where(User.referral_code == code, Community.is_active.is_(True))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_pending_for_person(session: AsyncSession, community_id: int, referred_telegram_id: int) -> PendingReferral | None:
    return (
        await session.execute(
            select(PendingReferral)
            .where(
                PendingReferral.community_id == community_id,
                PendingReferral.referred_telegram_id == referred_telegram_id,
                PendingReferral.status == ReferralStatus.PENDING,
            )
            .order_by(PendingReferral.created_at.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def register_referral_click(
    session: AsyncSession,
    community: Community,
    referrer_code: str,
    referred_telegram_id: int,
    referred_username: str | None,
    referred_is_bot: bool,
) -> tuple[bool, str, PendingReferral | None]:
    """Register attribution. If the person already joined verification, credit immediately."""
    if referred_is_bot:
        return False, "bot", None

    referrer = (
        await session.execute(
            select(User).where(User.referral_code == referrer_code, User.community_id == community.id).with_for_update()
        )
    ).scalar_one_or_none()
    if referrer is None:
        return False, "invalid_code", None
    if referrer.is_banned:
        return False, "referrer_banned", None
    if referrer.telegram_id == referred_telegram_id:
        return False, "self", None

    existing = await _get_pending_for_person(session, community.id, referred_telegram_id)
    if existing is not None:
        if existing.referrer_user_id == referrer.id:
            referred_user = (await session.execute(
                select(User).where(User.community_id == community.id, User.telegram_id == referred_telegram_id)
            )).scalar_one_or_none()
            if referred_user is not None and referred_user.has_joined_verification_group:
                return True, "pending_joined", existing
            return True, "already_pending", existing
        return False, "duplicate", existing

    referred_user = (
        await session.execute(
            select(User).where(User.community_id == community.id, User.telegram_id == referred_telegram_id)
        )
    ).scalar_one_or_none()
    if referred_user is not None and referred_user.is_banned:
        return False, "referred_banned", None

    pending = PendingReferral(
        community_id=community.id,
        referrer_user_id=referrer.id,
        referred_telegram_id=referred_telegram_id,
        referred_username=referred_username,
        status=ReferralStatus.PENDING,
    )
    session.add(pending)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await _get_pending_for_person(session, community.id, referred_telegram_id)
        return (False, "duplicate", existing)

    # The caller will immediately run the normal confirmation transaction if the user
    # has already joined, so Premium unlock remains centralized and retryable.
    return True, "pending_created", pending


async def confirm_referral_on_join(
    session: AsyncSession,
    community: Community,
    referred_telegram_id: int,
) -> tuple[User, int] | None:
    pending = await _get_pending_for_person(session, community.id, referred_telegram_id)
    if pending is None:
        return None

    now = datetime.now(timezone.utc)
    if pending.created_at + timedelta(hours=settings.INVITE_EXPIRY_HOURS) <= now:
        pending.status = ReferralStatus.EXPIRED
        pending.resolved_at = now
        return None

    referred_user = (
        await session.execute(
            select(User).where(User.community_id == community.id, User.telegram_id == referred_telegram_id).with_for_update()
        )
    ).scalar_one_or_none()
    referrer = await session.get(User, pending.referrer_user_id, with_for_update=True)
    if referred_user is None or referrer is None:
        pending.status = ReferralStatus.REJECTED_DUPLICATE
        pending.resolved_at = now
        return None
    if referrer.is_banned:
        pending.status = ReferralStatus.REJECTED_DUPLICATE
        pending.resolved_at = now
        return None
    if referred_user.telegram_id == referrer.telegram_id:
        pending.status = ReferralStatus.REJECTED_SELF
        pending.resolved_at = now
        return None
    if referred_user.is_banned:
        pending.status = ReferralStatus.REJECTED_DUPLICATE
        pending.resolved_at = now
        return None
    if referred_user.referred_by_user_id not in (None, referrer.id):
        pending.status = ReferralStatus.REJECTED_DUPLICATE
        pending.resolved_at = now
        return None

    pending.status = ReferralStatus.COUNTED
    pending.resolved_at = now
    referred_user.referred_by_user_id = referrer.id
    # Sessions use autoflush=False. Flush the state change before counting so the
    # progress query sees this referral as COUNTED instead of the old PENDING row.
    await session.flush()
    completed = await get_referral_progress(session, referrer.id)
    return referrer, completed


async def get_referral_progress(session: AsyncSession, user_id: int) -> int:
    return int(
        (await session.execute(
            select(func.count(PendingReferral.id)).where(
                PendingReferral.referrer_user_id == user_id,
                PendingReferral.status == ReferralStatus.COUNTED,
            )
        )).scalar_one()
    )
