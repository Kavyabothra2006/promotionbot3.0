"""add per-community cleanup schedule and tracked cleanup messages

Revision ID: 0009_ui_cleanup_schedule
Revises: 0008_release_hardening
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_ui_cleanup_schedule"
down_revision = "0008_release_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("communities")}
    if "cleanup_frequency" not in cols:
        op.add_column("communities", sa.Column("cleanup_frequency", sa.String(length=16), nullable=False, server_default="daily"))
    if "cleanup_last_run_at" not in cols:
        op.add_column("communities", sa.Column("cleanup_last_run_at", sa.DateTime(timezone=True), nullable=True))
    if "cleanup_messages" not in inspector.get_table_names():
        op.create_table(
            "cleanup_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("community_id", sa.Integer(), sa.ForeignKey("communities.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chat_id", sa.BigInteger(), nullable=False),
            sa.Column("message_id", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_cleanup_messages_community_id", "cleanup_messages", ["community_id"])
        op.create_index("ix_cleanup_messages_due", "cleanup_messages", ["community_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "cleanup_messages" in inspector.get_table_names():
        op.drop_index("ix_cleanup_messages_due", table_name="cleanup_messages")
        op.drop_index("ix_cleanup_messages_community_id", table_name="cleanup_messages")
        op.drop_table("cleanup_messages")
    cols = {c["name"] for c in inspector.get_columns("communities")}
    if "cleanup_last_run_at" in cols:
        op.drop_column("communities", "cleanup_last_run_at")
    if "cleanup_frequency" in cols:
        op.drop_column("communities", "cleanup_frequency")
