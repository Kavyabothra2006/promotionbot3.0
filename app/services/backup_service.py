from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.referral_code import generate_referral_code

from app.database.models import (
    AdminRole,
    BroadcastDelivery,
    BroadcastDeliveryStatus,
    BroadcastLog,
    BroadcastScope,
    BroadcastStatus,
    Community,
    CommunityAdmin,
    PendingReferral,
    PremiumInvite,
    PremiumInviteStatus,
    PurchaseRequest,
    PurchaseRequestStatus,
    ReferralStatus,
    UnlockFeedMessage,
    UnlockMethod,
    User,
    MediaType,
    BroadcastContentType,
)



def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def export_backup(session: AsyncSession, community_id: int) -> dict[str, Any]:
    community = await session.get(Community, community_id)
    if community is None:
        raise ValueError("Community not found")

    admins = (await session.execute(select(CommunityAdmin).where(CommunityAdmin.community_id == community_id))).scalars().all()
    users = (await session.execute(select(User).where(User.community_id == community_id))).scalars().all()
    referrals = (await session.execute(select(PendingReferral).where(PendingReferral.community_id == community_id))).scalars().all()
    invites = (await session.execute(select(PremiumInvite).where(PremiumInvite.community_id == community_id))).scalars().all()
    purchases = (await session.execute(select(PurchaseRequest).where(PurchaseRequest.community_id == community_id))).scalars().all()
    feed = (await session.execute(select(UnlockFeedMessage).where(UnlockFeedMessage.community_id == community_id))).scalars().all()
    broadcasts = (await session.execute(select(BroadcastLog).where(BroadcastLog.community_id == community_id))).scalars().all()
    broadcast_ids = [b.id for b in broadcasts]
    deliveries = []
    if broadcast_ids:
        deliveries = (await session.execute(select(BroadcastDelivery).where(BroadcastDelivery.broadcast_id.in_(broadcast_ids)))).scalars().all()

    return {
        "version": 3,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "community": {
            "name": community.name,
            "verification_chat_id": community.verification_chat_id,
            "premium_chat_id": community.premium_chat_id,
            "verification_invite_link": community.verification_invite_link,
            "welcome_media_type": community.welcome_media_type.value,
            "welcome_media_file_id": community.welcome_media_file_id,
            "welcome_text": community.welcome_text,
            "welcome_button_text": community.welcome_button_text,
            "referral_target": community.referral_target,
            "remove_on_premium_leave": community.remove_on_premium_leave,
            "delete_join_leave_messages": community.delete_join_leave_messages,
            "cleanup_frequency": community.cleanup_frequency,
            "cleanup_last_run_at": _dt(community.cleanup_last_run_at),
            "is_active": community.is_active,
        },
        "admins": [{"telegram_id": a.telegram_id, "role": a.role.value} for a in admins],
        "users": [
            {
                "old_id": u.id,
                "telegram_id": u.telegram_id,
                "username": u.username,
                "first_name": u.first_name,
                "referral_code": u.referral_code,
                "referred_by_old_id": u.referred_by_user_id,
                "is_premium": u.is_premium,
                "premium_unlocked_at": _dt(u.premium_unlocked_at),
                "premium_unlock_method": u.premium_unlock_method.value,
                "is_banned": u.is_banned,
                "has_joined_verification_group": u.has_joined_verification_group,
                "joined_verification_at": _dt(u.joined_verification_at),
                "joined_premium_at": _dt(u.joined_premium_at),
                "created_at": _dt(u.created_at),
            }
            for u in users
        ],
        "pending_referrals": [
            {
                "old_id": p.id,
                "referrer_old_user_id": p.referrer_user_id,
                "referred_telegram_id": p.referred_telegram_id,
                "referred_username": p.referred_username,
                "status": p.status.value,
                "created_at": _dt(p.created_at),
                "resolved_at": _dt(p.resolved_at),
            }
            for p in referrals
        ],
        "premium_invites": [
            {
                "old_id": i.id,
                "user_old_id": i.user_id,
                "invite_link": i.invite_link,
                "status": i.status.value,
                "created_at": _dt(i.created_at),
                "expires_at": _dt(i.expires_at),
                "used_at": _dt(i.used_at),
                "revoked_at": _dt(i.revoked_at),
                "approved_at": _dt(i.approved_at),
            }
            for i in invites
        ],
        "purchase_requests": [
            {
                "old_id": r.id,
                "user_old_id": r.user_id,
                "status": r.status.value,
                "created_at": _dt(r.created_at),
                "updated_at": _dt(r.updated_at),
            }
            for r in purchases
        ],
        "unlock_feed_messages": [
            {"chat_id": m.chat_id, "message_id": m.message_id, "created_at": _dt(m.created_at)}
            for m in feed
        ],
        "broadcasts": [
            {
                "old_id": b.id,
                "admin_telegram_id": b.admin_telegram_id,
                "scope": b.scope.value,
                "status": b.status.value,
                "total_count": b.total_count,
                "content_type": b.content_type.value,
                "content_file_id": b.content_file_id,
                "content_text": b.content_text,
                "sent_count": b.sent_count,
                "failed_count": b.failed_count,
                "last_processed_telegram_id": b.last_processed_telegram_id,
                "started_at": _dt(b.started_at),
                "finished_at": _dt(b.finished_at),
                "created_at": _dt(b.created_at),
            }
            for b in broadcasts
        ],
        "broadcast_deliveries": [
            {
                "broadcast_old_id": d.broadcast_id,
                "telegram_id": d.telegram_id,
                "status": d.status.value,
                "attempts": d.attempts,
                "sent_at": _dt(d.sent_at),
                "last_error": d.last_error,
            }
            for d in deliveries
        ],
    }


async def import_backup(session: AsyncSession, data: dict[str, Any]) -> Community:
    if not isinstance(data, dict) or data.get("version") not in (2, 3):
        raise ValueError("Unsupported backup version; expected 2 or 3")
    for key in ("admins", "users", "pending_referrals", "premium_invites", "purchase_requests", "unlock_feed_messages", "broadcasts", "broadcast_deliveries"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"Backup field '{key}' must be a list")
    c = data.get("community")
    if not isinstance(c, dict):
        raise ValueError("Missing community object")
    required = {
        "name", "verification_chat_id", "premium_chat_id", "welcome_media_type", "welcome_text",
        "welcome_button_text", "referral_target", "remove_on_premium_leave", "delete_join_leave_messages", "is_active",
    }
    missing = sorted(required - set(c))
    if missing:
        raise ValueError(f"Missing community fields: {', '.join(missing)}")
    if not isinstance(c["name"], str) or not c["name"].strip():
        raise ValueError("Community name must be non-empty")
    if not isinstance(c["referral_target"], int) or not 1 <= c["referral_target"] <= 10:
        raise ValueError("Invalid referral_target")

    result = await session.execute(select(Community).where(Community.verification_chat_id == c["verification_chat_id"]))
    community = result.scalar_one_or_none()
    premium_owner = None
    if c.get("premium_chat_id") is not None:
        premium_owner = (await session.execute(
            select(Community).where(Community.premium_chat_id == c["premium_chat_id"])
        )).scalar_one_or_none()
        if premium_owner is not None and (community is None or premium_owner.id != community.id):
            raise ValueError("Premium chat ID is already assigned to another community")
    if community is None:
        community = Community(verification_chat_id=c["verification_chat_id"], name=c["name"])
        session.add(community)
    community.name = c["name"]
    community.premium_chat_id = c["premium_chat_id"]
    community.verification_invite_link = c.get("verification_invite_link")
    community.welcome_media_type = MediaType(c["welcome_media_type"])
    community.welcome_media_file_id = c.get("welcome_media_file_id")
    community.welcome_text = c["welcome_text"]
    community.welcome_button_text = c["welcome_button_text"]
    community.referral_target = c["referral_target"]
    community.remove_on_premium_leave = bool(c["remove_on_premium_leave"])
    community.delete_join_leave_messages = bool(c["delete_join_leave_messages"])
    community.cleanup_frequency = c.get("cleanup_frequency", "daily")
    community.cleanup_last_run_at = _parse_dt(c.get("cleanup_last_run_at"))
    community.is_active = bool(c["is_active"])
    await session.flush()

    for a in data.get("admins", []):
        if not isinstance(a, dict):
            continue
        existing = (await session.execute(select(CommunityAdmin).where(
            CommunityAdmin.community_id == community.id, CommunityAdmin.telegram_id == int(a["telegram_id"])
        ))).scalar_one_or_none()
        if existing is None:
            session.add(CommunityAdmin(community_id=community.id, telegram_id=int(a["telegram_id"]), role=AdminRole(a["role"])))
        else:
            existing.role = AdminRole(a["role"])

    old_to_new: dict[int, int] = {}
    for u in data.get("users", []):
        result = await session.execute(select(User).where(User.community_id == community.id, User.telegram_id == int(u["telegram_id"])))
        user = result.scalar_one_or_none()
        if user is None:
            referral_code = str(u.get("referral_code") or "")
            if not referral_code or (await session.execute(select(User.id).where(User.referral_code == referral_code).limit(1))).scalar_one_or_none() is not None:
                while True:
                    referral_code = generate_referral_code()
                    collision = (await session.execute(select(User.id).where(User.referral_code == referral_code).limit(1))).scalar_one_or_none()
                    if collision is None:
                        break
            user = User(community_id=community.id, telegram_id=int(u["telegram_id"]), referral_code=referral_code)
            session.add(user)
        user.username = u.get("username")
        user.first_name = u.get("first_name") or ""
        user.is_premium = bool(u.get("is_premium"))
        user.premium_unlocked_at = _parse_dt(u.get("premium_unlocked_at"))
        user.premium_unlock_method = UnlockMethod(u.get("premium_unlock_method", UnlockMethod.NONE.value))
        user.is_banned = bool(u.get("is_banned"))
        user.has_joined_verification_group = bool(u.get("has_joined_verification_group"))
        user.joined_verification_at = _parse_dt(u.get("joined_verification_at"))
        user.joined_premium_at = _parse_dt(u.get("joined_premium_at"))
        await session.flush()
        old_to_new[int(u["old_id"])] = user.id

    for u in data.get("users", []):
        new_id = old_to_new.get(int(u["old_id"]))
        ref_id = old_to_new.get(int(u["referred_by_old_id"])) if u.get("referred_by_old_id") is not None else None
        if new_id and ref_id:
            user = await session.get(User, new_id)
            user.referred_by_user_id = ref_id

    for r in data.get("pending_referrals", []):
        ref = old_to_new.get(int(r["referrer_old_user_id"]))
        if not ref:
            continue
        exists = (await session.execute(select(PendingReferral).where(
            PendingReferral.community_id == community.id,
            PendingReferral.referrer_user_id == ref,
            PendingReferral.referred_telegram_id == int(r["referred_telegram_id"]),
            PendingReferral.created_at == (_parse_dt(r.get("created_at")) or datetime.now(timezone.utc)),
        ))).scalar_one_or_none()
        if exists is None:
            session.add(PendingReferral(
                community_id=community.id,
                referrer_user_id=ref,
                referred_telegram_id=int(r["referred_telegram_id"]),
                referred_username=r.get("referred_username"),
                status=ReferralStatus(r["status"]),
                created_at=_parse_dt(r.get("created_at")) or datetime.now(timezone.utc),
                resolved_at=_parse_dt(r.get("resolved_at")),
            ))

    for i in data.get("premium_invites", []):
        new_user = old_to_new.get(int(i["user_old_id"]))
        if not new_user:
            continue
        exists = (await session.execute(select(PremiumInvite).where(PremiumInvite.invite_link == i["invite_link"]))).scalar_one_or_none()
        if exists is None:
            session.add(PremiumInvite(
                community_id=community.id,
                user_id=new_user,
                invite_link=i["invite_link"],
                status=PremiumInviteStatus(i["status"]),
                created_at=_parse_dt(i.get("created_at")) or datetime.now(timezone.utc),
                expires_at=_parse_dt(i.get("expires_at")) or datetime.now(timezone.utc) + timedelta(hours=1),
                used_at=_parse_dt(i.get("used_at")),
                revoked_at=_parse_dt(i.get("revoked_at")),
                approved_at=_parse_dt(i.get("approved_at")),
            ))

    for r in data.get("purchase_requests", []):
        new_user = old_to_new.get(int(r["user_old_id"]))
        if not new_user:
            continue
        created_at = _parse_dt(r.get("created_at")) or datetime.now(timezone.utc)
        status = PurchaseRequestStatus(r.get("status", PurchaseRequestStatus.PENDING.value))
        if status == PurchaseRequestStatus.PENDING:
            pending_existing = (await session.execute(select(PurchaseRequest).where(
                PurchaseRequest.community_id == community.id,
                PurchaseRequest.user_id == new_user,
                PurchaseRequest.status == PurchaseRequestStatus.PENDING,
            ))).scalar_one_or_none()
            if pending_existing is not None:
                continue
        existing = (await session.execute(select(PurchaseRequest).where(
            PurchaseRequest.community_id == community.id,
            PurchaseRequest.user_id == new_user,
            PurchaseRequest.created_at == created_at,
        ))).scalar_one_or_none()
        if existing is None:
            session.add(PurchaseRequest(
                community_id=community.id,
                user_id=new_user,
                status=status,
                created_at=_parse_dt(r.get("created_at")) or datetime.now(timezone.utc),
                updated_at=_parse_dt(r.get("updated_at")) or datetime.now(timezone.utc),
            ))

    for m in data.get("unlock_feed_messages", []):
        existing = (await session.execute(select(UnlockFeedMessage).where(
            UnlockFeedMessage.community_id == community.id,
            UnlockFeedMessage.chat_id == int(m["chat_id"]),
            UnlockFeedMessage.message_id == int(m["message_id"]),
        ))).scalar_one_or_none()
        if existing is None:
            session.add(UnlockFeedMessage(
                community_id=community.id,
                chat_id=int(m["chat_id"]),
                message_id=int(m["message_id"]),
                created_at=_parse_dt(m.get("created_at")) or datetime.now(timezone.utc),
            ))

    broadcast_old_to_new: dict[int, int] = {}
    for b in data.get("broadcasts", []):
        old_id = int(b.get("old_id", 0))
        created_at = _parse_dt(b.get("created_at")) or datetime.now(timezone.utc)
        existing = (await session.execute(select(BroadcastLog).where(
            BroadcastLog.community_id == community.id,
            BroadcastLog.admin_telegram_id == int(b["admin_telegram_id"]),
            BroadcastLog.created_at == created_at,
            BroadcastLog.content_type == BroadcastContentType(b["content_type"]),
        ))).scalar_one_or_none()
        if existing is None:
            existing = BroadcastLog(
                community_id=community.id,
                admin_telegram_id=int(b["admin_telegram_id"]),
                scope=BroadcastScope(b["scope"]),
                status=BroadcastStatus(b["status"]),
                total_count=int(b.get("total_count", 0)),
                content_type=BroadcastContentType(b["content_type"]),
                content_file_id=b.get("content_file_id"),
                content_text=b.get("content_text"),
                sent_count=int(b.get("sent_count", 0)),
                failed_count=int(b.get("failed_count", 0)),
                last_processed_telegram_id=b.get("last_processed_telegram_id"),
                started_at=_parse_dt(b.get("started_at")),
                finished_at=_parse_dt(b.get("finished_at")),
                created_at=created_at,
            )
            # Never restore an active worker as RUNNING; it will be recovered safely.
            if existing.status == BroadcastStatus.RUNNING:
                existing.status = BroadcastStatus.PENDING
            session.add(existing)
            await session.flush()
        broadcast_old_to_new[old_id] = existing.id

    for d in data.get("broadcast_deliveries", []):
        new_broadcast = broadcast_old_to_new.get(int(d["broadcast_old_id"]))
        if not new_broadcast:
            continue
        exists = (await session.execute(select(BroadcastDelivery).where(
            BroadcastDelivery.broadcast_id == new_broadcast,
            BroadcastDelivery.telegram_id == int(d["telegram_id"]),
        ))).scalar_one_or_none()
        if exists is None:
            session.add(BroadcastDelivery(
                broadcast_id=new_broadcast,
                telegram_id=int(d["telegram_id"]),
                status=BroadcastDeliveryStatus(d["status"]),
                attempts=int(d.get("attempts", 0)),
                sent_at=_parse_dt(d.get("sent_at")),
                last_error=d.get("last_error"),
            ))

    await session.flush()
    return community
