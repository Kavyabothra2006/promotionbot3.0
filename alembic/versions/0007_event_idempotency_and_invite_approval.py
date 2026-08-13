"""add Telegram update idempotency and Premium invite approval timestamp

Revision ID: 0007_event_idempotency_and_invite_approval
Revises: 0006_referral_invite_delivery_integrity
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_event_idempotency_and_invite_approval"
down_revision = "0006_referral_invite_delivery_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("update_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_processed_updates_update_id", "processed_updates", ["update_id"])
    op.add_column("premium_invites", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("premium_invites", "approved_at")
    op.drop_index("ix_processed_updates_update_id", table_name="processed_updates")
    op.drop_table("processed_updates")
