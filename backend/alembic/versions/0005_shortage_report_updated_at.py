"""shortage reports remember when they were last updated

A second report for the same pantry, category and week now updates the first, so the row needs to
say when that last happened.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shortage_reports",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("shortage_reports", "updated_at")
