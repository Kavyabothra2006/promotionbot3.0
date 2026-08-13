"""add production data constraints

Revision ID: 0005_production_constraints
Revises: 0004_broadcast_resume_cursor
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_production_constraints"
down_revision = "0004_broadcast_resume_cursor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_communities_referral_target_1_10",
        "communities",
        sa.text("referral_target BETWEEN 1 AND 10"),
    )


def downgrade() -> None:
    op.drop_constraint("ck_communities_referral_target_1_10", "communities", type_="check")
