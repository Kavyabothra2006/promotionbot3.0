"""add resumable broadcast cursor

Revision ID: 0004_broadcast_resume_cursor
Revises: 0003_pending_purchase_unique
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_broadcast_resume_cursor"
down_revision = "0003_pending_purchase_unique"
branch_labels = None
depends_on = None

def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {c["name"] for c in inspector.get_columns(table_name)}

def upgrade() -> None:
    if not _has_column("broadcast_logs", "last_processed_telegram_id"):
        op.add_column("broadcast_logs", sa.Column("last_processed_telegram_id", sa.BigInteger(), nullable=True))

def downgrade() -> None:
    if _has_column("broadcast_logs", "last_processed_telegram_id"):
        op.drop_column("broadcast_logs", "last_processed_telegram_id")
