"""login lockout counter

Failed login attempts per email and per address, kept in the database so that every API instance
sees the same counts (CLAUDE.md rule 4). Keys are SHA-256 hashes.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_throttle",
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("first_failure_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("key_hash", name="pk_login_throttle"),
        sa.CheckConstraint("failures >= 0", name="ck_login_throttle_failures_nonneg"),
    )


def downgrade() -> None:
    op.drop_table("login_throttle")
