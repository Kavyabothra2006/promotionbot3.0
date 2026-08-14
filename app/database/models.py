from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def _enum(python_enum: type[enum.Enum]):
    return SAEnum(python_enum, values_callable=lambda e: [m.value for m in e], native_enum=False)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class MediaType(str, enum.Enum):
    NONE = "none"
    PHOTO = "photo"
    VIDEO = "video"
    ANIMATION = "animation"
    STICKER = "sticker"


class UnlockMethod(str, enum.Enum):
    NONE = "none"
    REFERRAL = "referral"
    MANUAL = "manual"


class ReferralStatus(str, enum.Enum):
    PENDING = "pending"       # deep-link clicked, not yet joined the group
    COUNTED = "counted"       # confirmed join, credited to referrer
    REJECTED_SELF = "rejected_self"
    REJECTED_DUPLICATE = "rejected_duplicate"
    REJECTED_BOT = "rejected_bot"
    EXPIRED = "expired"


class PremiumInviteStatus(str, enum.Enum):
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PurchaseRequestStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class AdminRole(str, enum.Enum):
    OWNER = "owner"
    MODERATOR = "moderator"


class BroadcastScope(str, enum.Enum):
    ALL = "all"
    PREMIUM_ONLY = "premium_only"


class BroadcastContentType(str, enum.Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    STICKER = "sticker"
    ANIMATION = "animation"


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"
    __table_args__ = (Index("ix_processed_updates_processed_at", "processed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BroadcastDeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class BroadcastStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# Community
# --------------------------------------------------------------------------- #

class Community(Base):
    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))

    verification_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    premium_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    verification_invite_link: Mapped[str | None] = mapped_column(String(255), nullable=True)

    welcome_media_type: Mapped[MediaType] = mapped_column(_enum(MediaType), default=MediaType.NONE)
    welcome_media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    welcome_text: Mapped[str] = mapped_column(
        Text,
        default="🎉 Welcome, {name}!\n\nComplete the steps below to unlock Premium access.",
    )
    welcome_button_text: Mapped[str] = mapped_column(String(64), default="🚀 Start Verification")

    referral_target: Mapped[int] = mapped_column(Integer, default=2)
    remove_on_premium_leave: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_join_leave_messages: Mapped[bool] = mapped_column(Boolean, default=True)
    cleanup_frequency: Mapped[str] = mapped_column(String(16), default="daily")
    cleanup_last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    admins: Mapped[list["CommunityAdmin"]] = relationship(back_populates="community", cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship(back_populates="community", cascade="all, delete-orphan")


class CleanupMessage(Base):
    __tablename__ = "cleanup_messages"
    __table_args__ = (Index("ix_cleanup_messages_due", "community_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommunityAdmin(Base):
    __tablename__ = "community_admins"
    __table_args__ = (UniqueConstraint("community_id", "telegram_id", name="uq_admin_per_community"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role: Mapped[AdminRole] = mapped_column(_enum(AdminRole), default=AdminRole.MODERATOR)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    community: Mapped[Community] = relationship(back_populates="admins")


# --------------------------------------------------------------------------- #
# User
# --------------------------------------------------------------------------- #

class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("community_id", "telegram_id", name="uq_user_per_community"),
        UniqueConstraint("referral_code", name="uq_users_referral_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)

    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), default="")

    referral_code: Mapped[str] = mapped_column(String(16))
    referred_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    premium_unlocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    premium_unlock_method: Mapped[UnlockMethod] = mapped_column(_enum(UnlockMethod), default=UnlockMethod.NONE)

    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    has_joined_verification_group: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_verification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_premium_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    community: Mapped[Community] = relationship(back_populates="users")
    referred_by: Mapped["User | None"] = relationship(remote_side=[id])


class PendingReferral(Base):
    """Immutable referral-attribution attempts; only one pending attempt per person/community."""

    __tablename__ = "pending_referrals"
    __table_args__ = (
        Index(
            "uq_pending_referral_per_person",
            "community_id",
            "referred_telegram_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_pending_referral_history", "community_id", "referred_telegram_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    referrer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    referred_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    referred_username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ReferralStatus] = mapped_column(_enum(ReferralStatus), default=ReferralStatus.PENDING, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PremiumInvite(Base):
    __tablename__ = "premium_invites"
    __table_args__ = (
        Index("ix_premium_invites_user_community_status", "user_id", "community_id", "status"),
        Index(
            "uq_active_premium_invite_per_user",
            "user_id",
            "community_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    invite_link: Mapped[str] = mapped_column(String(255))
    status: Mapped[PremiumInviteStatus] = mapped_column(
        _enum(PremiumInviteStatus),
        default=PremiumInviteStatus.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()
    community: Mapped[Community] = relationship()


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"
    __table_args__ = (
        Index(
            "ix_purchase_requests_user_community_status",
            "user_id",
            "community_id",
            "status",
        ),
        Index(
            "uq_purchase_requests_one_pending",
            "community_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[PurchaseRequestStatus] = mapped_column(
        _enum(PurchaseRequestStatus),
        default=PurchaseRequestStatus.PENDING,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UnlockFeedMessage(Base):
    """Tracks unlock-announcement messages posted in a community group so old ones can be pruned."""

    __tablename__ = "unlock_feed_messages"
    __table_args__ = (Index("ix_unlock_feed_community_created", "community_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BroadcastLog(Base):
    __tablename__ = "broadcast_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger)

    scope: Mapped[BroadcastScope] = mapped_column(_enum(BroadcastScope), default=BroadcastScope.ALL)
    status: Mapped[BroadcastStatus] = mapped_column(_enum(BroadcastStatus), default=BroadcastStatus.PENDING, index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[BroadcastContentType] = mapped_column(_enum(BroadcastContentType))
    content_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    last_processed_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BroadcastDelivery(Base):
    __tablename__ = "broadcast_deliveries"
    __table_args__ = (
        UniqueConstraint("broadcast_id", "telegram_id", name="uq_broadcast_recipient"),
        Index("ix_broadcast_delivery_pending", "broadcast_id", "status", "telegram_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(
        ForeignKey("broadcast_logs.id", ondelete="CASCADE"), index=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[BroadcastDeliveryStatus] = mapped_column(
        _enum(BroadcastDeliveryStatus), default=BroadcastDeliveryStatus.PENDING, nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

