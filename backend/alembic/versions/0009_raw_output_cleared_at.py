"""raw model output retention marker

`donations.raw_output_cleared_at` records when the weekly refresh cleared the raw model output
(90 days after review). A check constraint keeps the marker honest: it can be set only when the
output is gone and the donation has been reviewed.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "donations", sa.Column("raw_output_cleared_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "raw_cleared_after_review",
        "donations",
        "raw_output_cleared_at IS NULL OR (raw_llm_output IS NULL AND status <> 'pending_review')",
    )


def downgrade() -> None:
    op.drop_constraint("raw_cleared_after_review", "donations", type_="check")
    op.drop_column("donations", "raw_output_cleared_at")
