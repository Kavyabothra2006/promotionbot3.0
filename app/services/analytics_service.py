from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PendingReferral, PurchaseRequest, ReferralStatus, User


async def community_stats(session: AsyncSession, community_id: int) -> dict:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)

    async def count(stmt) -> int:
        return int((await session.execute(stmt)).scalar_one())

    base = select(func.count()).select_from(User).where(User.community_id == community_id)
    total_users = await count(base)
    premium_users = await count(base.where(User.is_premium.is_(True)))
    banned_users = await count(base.where(User.is_banned.is_(True)))
    joins_today = await count(base.where(User.joined_verification_at >= today_start))
    joins_week = await count(base.where(User.joined_verification_at >= week_start))
    unlocks_today = await count(base.where(User.premium_unlocked_at >= today_start))
    premium_joins_week = await count(base.where(User.joined_premium_at >= week_start))

    referrals_completed = await count(
        select(func.count()).select_from(PendingReferral).where(
            PendingReferral.community_id == community_id,
            PendingReferral.status == ReferralStatus.COUNTED,
        )
    )
    referrals_pending = await count(
        select(func.count()).select_from(PendingReferral).where(
            PendingReferral.community_id == community_id,
            PendingReferral.status == ReferralStatus.PENDING,
        )
    )
    purchase_requests = await count(
        select(func.count()).select_from(PurchaseRequest).where(PurchaseRequest.community_id == community_id)
    )
    referrals_started = await count(
        select(func.count()).select_from(PendingReferral).where(PendingReferral.community_id == community_id)
    )

    conversion_rate = round((premium_users / total_users) * 100, 1) if total_users else 0.0
    referral_success_rate = round((referrals_completed / referrals_started) * 100, 1) if referrals_started else 0.0
    unlock_rate = round((unlocks_today / joins_today) * 100, 1) if joins_today else 0.0

    top_result = await session.execute(
        select(User.first_name, User.username, User.telegram_id, func.count(PendingReferral.id).label("completed"))
        .join(PendingReferral, PendingReferral.referrer_user_id == User.id)
        .where(User.community_id == community_id, PendingReferral.status == ReferralStatus.COUNTED)
        .group_by(User.id)
        .order_by(desc("completed"))
        .limit(5)
    )
    most_active_users = [
        {"name": name or str(telegram_id), "username": username, "telegram_id": telegram_id, "referrals": int(completed)}
        for name, username, telegram_id, completed in top_result.all()
    ]

    return {
        "total_users": total_users,
        "premium_users": premium_users,
        "banned_users": banned_users,
        "joins_today": joins_today,
        "joins_week": joins_week,
        "unlocks_today": unlocks_today,
        "premium_joins_week": premium_joins_week,
        "referrals_completed": referrals_completed,
        "referrals_pending": referrals_pending,
        "referrals_started": referrals_started,
        "referral_success_rate": referral_success_rate,
        "unlock_rate": unlock_rate,
        "purchase_requests": purchase_requests,
        "conversion_rate": conversion_rate,
        "most_active_users": most_active_users,
    }


async def daily_growth(session: AsyncSession, community_id: int, days: int = 7) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days) - 1)
    result = await session.execute(
        select(func.date(User.joined_verification_at).label("day"), func.count(User.id))
        .where(User.community_id == community_id, User.joined_verification_at >= cutoff)
        .group_by(func.date(User.joined_verification_at))
        .order_by(func.date(User.joined_verification_at))
    )
    return [{"day": str(day), "joins": int(count)} for day, count in result.all()]
