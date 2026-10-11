"""database-backed rate limits

One row per user and endpoint holds a counter for a one-hour window (see app/security/rate_limit.py).
The key is a SHA-256 hash, so the table holds no user ids.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limits",
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key_hash", name="pk_rate_limits"),
        sa.CheckConstraint("count >= 0", name="ck_rate_limits_count_nonneg"),
    )


def downgrade() -> None:
    op.drop_table("rate_limits")
