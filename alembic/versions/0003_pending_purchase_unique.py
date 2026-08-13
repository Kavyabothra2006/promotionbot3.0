"""enforce one pending purchase request per user and community

Revision ID: 0003_pending_purchase_unique
Revises: 0002_broadcast_job_fields
Create Date: 2026-08-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_pending_purchase_unique"
down_revision = "0002_broadcast_job_fields"
branch_labels = None
depends_on = None

def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return index_name in {i["name"] for i in inspector.get_indexes(table_name)}

def upgrade() -> None:
    op.execute(sa.text("""
        DELETE FROM purchase_requests
        WHERE status = 'pending'
          AND id NOT IN (
              SELECT MIN(id)
              FROM purchase_requests
              WHERE status = 'pending'
              GROUP BY community_id, user_id
          )
    """))
    if not _has_index("purchase_requests", "uq_purchase_requests_one_pending"):
        op.create_index(
            "uq_purchase_requests_one_pending",
            "purchase_requests",
            ["community_id", "user_id"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        )

def downgrade() -> None:
    if _has_index("purchase_requests", "uq_purchase_requests_one_pending"):
        op.drop_index("uq_purchase_requests_one_pending", table_name="purchase_requests")
