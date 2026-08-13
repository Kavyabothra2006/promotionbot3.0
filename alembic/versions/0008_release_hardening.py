"""release hardening: processed-update retention index and broadcast worker token

Revision ID: 0008_release_hardening
Revises: 0007_event_idempotency_invite
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_release_hardening"
down_revision = "0007_event_idempotency_invite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_processed_updates_processed_at", "processed_updates", ["processed_at"])
    op.add_column("broadcast_logs", sa.Column("worker_token", sa.String(length=64), nullable=True))
    op.create_index("ix_broadcast_logs_worker_token", "broadcast_logs", ["worker_token"])


def downgrade() -> None:
    op.drop_index("ix_broadcast_logs_worker_token", table_name="broadcast_logs")
    op.drop_column("broadcast_logs", "worker_token")
    op.drop_index("ix_processed_updates_processed_at", table_name="processed_updates")

