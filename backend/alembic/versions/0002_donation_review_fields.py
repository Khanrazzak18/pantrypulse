"""donation review fields: donor chosen during review, reviewer, original filename

A donation exists as `pending_review` before anyone has picked its donor, so `donor_id` becomes
nullable (enforced non-null once confirmed). Alembic does not detect CHECK constraints, so the two
new ones are written out here by hand.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("donations", sa.Column("original_filename", sa.String(length=255), nullable=True))
    op.add_column("donations", sa.Column("reviewed_by", sa.Integer(), nullable=True))
    op.add_column("donations", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("donations", "donor_id", existing_type=sa.INTEGER(), nullable=True)
    op.create_index(
        "ix_donations_status_created_at", "donations", ["status", "created_at"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_donations_reviewed_by_users"),
        "donations",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_donations_confirmed_has_donor"),
        "donations",
        "status <> 'confirmed' OR donor_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_donations_review_matches_status"),
        "donations",
        "(status = 'pending_review' AND reviewed_at IS NULL AND reviewed_by IS NULL) "
        "OR (status = 'rejected' AND reviewed_at IS NOT NULL) OR status = 'confirmed'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_donations_review_matches_status"), "donations", type_="check")
    op.drop_constraint(op.f("ck_donations_confirmed_has_donor"), "donations", type_="check")
    op.drop_constraint(op.f("fk_donations_reviewed_by_users"), "donations", type_="foreignkey")
    op.drop_index("ix_donations_status_created_at", table_name="donations")
    # Donations without a donor are unreviewed uploads (they hold no items or lots); donor_id
    # cannot go back to NOT NULL while they exist, so they are removed.
    op.execute("DELETE FROM donations WHERE donor_id IS NULL")
    op.alter_column("donations", "donor_id", existing_type=sa.INTEGER(), nullable=False)
    op.drop_column("donations", "reviewed_at")
    op.drop_column("donations", "reviewed_by")
    op.drop_column("donations", "original_filename")
