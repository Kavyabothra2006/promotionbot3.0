"""fix referral history, premium invite uniqueness, and durable broadcast recipients

Revision ID: 0006_referral_invite_integrity
Revises: 0005_production_constraints
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_referral_invite_integrity"
down_revision = "0005_production_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Replace the old one-row-ever-per-person referral rule with immutable history
    # plus one active/pending attribution per person.
    op.drop_constraint("uq_one_referral_record_per_person", "pending_referrals", type_="unique")
    op.create_index(
        "uq_pending_referral_per_person",
        "pending_referrals",
        ["community_id", "referred_telegram_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_pending_referral_history",
        "pending_referrals",
        ["community_id", "referred_telegram_id", "created_at"],
    )

    # Keep newest active invite before adding the invariant.
    op.execute(sa.text("""
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY user_id, community_id ORDER BY created_at DESC, id DESC
            ) AS rn
            FROM premium_invites
            WHERE status = 'active'
        )
        UPDATE premium_invites p
        SET status = 'revoked', revoked_at = NOW()
        FROM ranked r
        WHERE p.id = r.id AND r.rn > 1
    """))
    op.create_index(
        "uq_active_premium_invite_per_user",
        "premium_invites",
        ["user_id", "community_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "broadcast_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broadcast_id", sa.Integer(), sa.ForeignKey("broadcast_logs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("broadcast_id", "telegram_id", name="uq_broadcast_recipient"),
    )
    op.create_index("ix_broadcast_deliveries_broadcast_id", "broadcast_deliveries", ["broadcast_id"])
    op.create_index("ix_broadcast_deliveries_telegram_id", "broadcast_deliveries", ["telegram_id"])
    op.create_index(
        "ix_broadcast_delivery_pending",
        "broadcast_deliveries",
        ["broadcast_id", "status", "telegram_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_broadcast_delivery_pending", table_name="broadcast_deliveries")
    op.drop_index("ix_broadcast_deliveries_telegram_id", table_name="broadcast_deliveries")
    op.drop_index("ix_broadcast_deliveries_broadcast_id", table_name="broadcast_deliveries")
    op.drop_table("broadcast_deliveries")
    op.drop_index("uq_active_premium_invite_per_user", table_name="premium_invites")
    op.drop_index("ix_pending_referral_history", table_name="pending_referrals")
    op.drop_index("uq_pending_referral_per_person", table_name="pending_referrals")
    # The pre-0006 schema allowed only one referral row per person. Preserve the
    # newest referral record for each community/person pair before restoring that
    # invariant so the downgrade remains executable on databases containing history.
    op.execute(sa.text("""
        DELETE FROM pending_referrals p
        USING pending_referrals newer
        WHERE p.community_id = newer.community_id
          AND p.referred_telegram_id = newer.referred_telegram_id
          AND (p.created_at < newer.created_at
               OR (p.created_at = newer.created_at AND p.id < newer.id))
    """))
    op.create_unique_constraint(
        "uq_one_referral_record_per_person",
        "pending_referrals",
        ["community_id", "referred_telegram_id"],
    )

