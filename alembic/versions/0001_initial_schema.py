"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _enum(values):
    return sa.String(length=32)


def upgrade() -> None:
    op.create_table(
        "communities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("verification_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("premium_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("verification_invite_link", sa.String(length=255), nullable=True),
        sa.Column("welcome_media_type", _enum([]), nullable=False, server_default="none"),
        sa.Column("welcome_media_file_id", sa.String(length=255), nullable=True),
        sa.Column("welcome_text", sa.Text(), nullable=False, server_default="🎉 Welcome, {name}!\n\nComplete the steps below to unlock Premium access."),
        sa.Column("welcome_button_text", sa.String(length=64), nullable=False, server_default="🚀 Start Verification"),
        sa.Column("referral_target", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("remove_on_premium_leave", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delete_join_leave_messages", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("verification_chat_id"),
        sa.UniqueConstraint("premium_chat_id"),
    )
    op.create_index("ix_communities_verification_chat_id", "communities", ["verification_chat_id"], unique=True)

    op.create_table(
        "community_admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.Integer(), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("role", _enum([]), nullable=False, server_default="moderator"),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("community_id", "telegram_id", name="uq_admin_per_community"),
    )
    op.create_index("ix_community_admins_community_id", "community_admins", ["community_id"])
    op.create_index("ix_community_admins_telegram_id", "community_admins", ["telegram_id"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.Integer(), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("referral_code", sa.String(length=16), nullable=False),
        sa.Column("referred_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("premium_unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("premium_unlock_method", _enum([]), nullable=False, server_default="none"),
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_joined_verification_group", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("joined_verification_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_premium_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("community_id", "telegram_id", name="uq_user_per_community"),
        sa.UniqueConstraint("referral_code", name="uq_users_referral_code"),
    )
    op.create_index("ix_users_community_id", "users", ["community_id"])
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    op.create_table(
        "pending_referrals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.Integer(), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("referrer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("referred_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("referred_username", sa.String(length=255), nullable=True),
        sa.Column("status", _enum([]), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("community_id", "referred_telegram_id", name="uq_one_referral_record_per_person"),
    )
    op.create_index("ix_pending_referrals_community_id", "pending_referrals", ["community_id"])
    op.create_index("ix_pending_referrals_referrer_user_id", "pending_referrals", ["referrer_user_id"])
    op.create_index("ix_pending_referrals_referred_telegram_id", "pending_referrals", ["referred_telegram_id"])
    op.create_index("ix_pending_referrals_status", "pending_referrals", ["status"])

    op.create_table(
        "premium_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.Integer(), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("invite_link", sa.String(length=255), nullable=False),
        sa.Column("status", _enum([]), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_premium_invites_community_id", "premium_invites", ["community_id"])
    op.create_index("ix_premium_invites_user_id", "premium_invites", ["user_id"])
    op.create_index("ix_premium_invites_user_community_status", "premium_invites", ["user_id", "community_id", "status"])

    op.create_table(
        "purchase_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.Integer(), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", _enum([]), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_purchase_requests_community_id", "purchase_requests", ["community_id"])
    op.create_index("ix_purchase_requests_user_id", "purchase_requests", ["user_id"])
    op.create_index("ix_purchase_requests_user_community_status", "purchase_requests", ["user_id", "community_id", "status"])

    op.create_table(
        "unlock_feed_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.Integer(), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_unlock_feed_messages_community_id", "unlock_feed_messages", ["community_id"])
    op.create_index("ix_unlock_feed_community_created", "unlock_feed_messages", ["community_id", "created_at"])

    op.create_table(
        "broadcast_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.Integer(), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("scope", _enum([]), nullable=False, server_default="all"),
        sa.Column("content_type", _enum([]), nullable=False),
        sa.Column("content_file_id", sa.String(length=255), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_broadcast_logs_community_id", "broadcast_logs", ["community_id"])


def downgrade() -> None:
    op.drop_index("ix_broadcast_logs_community_id", table_name="broadcast_logs")
    op.drop_table("broadcast_logs")
    op.drop_index("ix_unlock_feed_community_created", table_name="unlock_feed_messages")
    op.drop_index("ix_unlock_feed_messages_community_id", table_name="unlock_feed_messages")
    op.drop_table("unlock_feed_messages")
    op.drop_index("ix_purchase_requests_user_community_status", table_name="purchase_requests")
    op.drop_index("ix_purchase_requests_user_id", table_name="purchase_requests")
    op.drop_index("ix_purchase_requests_community_id", table_name="purchase_requests")
    op.drop_table("purchase_requests")
    op.drop_index("ix_premium_invites_user_community_status", table_name="premium_invites")
    op.drop_index("ix_premium_invites_user_id", table_name="premium_invites")
    op.drop_index("ix_premium_invites_community_id", table_name="premium_invites")
    op.drop_table("premium_invites")
    op.drop_index("ix_pending_referrals_status", table_name="pending_referrals")
    op.drop_index("ix_pending_referrals_referred_telegram_id", table_name="pending_referrals")
    op.drop_index("ix_pending_referrals_referrer_user_id", table_name="pending_referrals")
    op.drop_index("ix_pending_referrals_community_id", table_name="pending_referrals")
    op.drop_table("pending_referrals")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_index("ix_users_community_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_community_admins_telegram_id", table_name="community_admins")
    op.drop_index("ix_community_admins_community_id", table_name="community_admins")
    op.drop_table("community_admins")
    op.drop_index("ix_communities_verification_chat_id", table_name="communities")
    op.drop_table("communities")
