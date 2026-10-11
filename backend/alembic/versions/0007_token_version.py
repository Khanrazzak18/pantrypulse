"""users get a token_version so sessions can be revoked

Logging out, deactivating a user or changing their role or password raises the version, which makes
every session token issued before it stop working (the version is a claim inside the token).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("token_version", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
