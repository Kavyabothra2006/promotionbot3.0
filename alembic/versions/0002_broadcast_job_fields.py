"""add persistent broadcast job fields

Revision ID: 0002_broadcast_job_fields
Revises: 0001_initial_schema
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_broadcast_job_fields"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {c["name"] for c in inspector.get_columns(table_name)}

def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index_name in {i["name"] for i in inspector.get_indexes(table_name)}

def upgrade() -> None:
    if not _has_column("broadcast_logs", "status"):
        op.add_column("broadcast_logs", sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"))
    if not _has_column("broadcast_logs", "total_count"):
        op.add_column("broadcast_logs", sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"))
    if not _has_column("broadcast_logs", "started_at"):
        op.add_column("broadcast_logs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column("broadcast_logs", "finished_at"):
        op.add_column("broadcast_logs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_index("broadcast_logs", "ix_broadcast_logs_status"):
        op.create_index("ix_broadcast_logs_status", "broadcast_logs", ["status"])

def downgrade() -> None:
    if _has_index("broadcast_logs", "ix_broadcast_logs_status"):
        op.drop_index("ix_broadcast_logs_status", table_name="broadcast_logs")
    for column in ("finished_at", "started_at", "total_count", "status"):
        if _has_column("broadcast_logs", column):
            op.drop_column("broadcast_logs", column)
