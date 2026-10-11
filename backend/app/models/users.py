from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    event,
    func,
    true,
)
from sqlalchemy.orm import Mapped, attributes, mapped_column

from app.constants import ROLES
from app.models.base import Base, in_list


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(in_list("role", ROLES), name="role_valid"),
        # A pantry manager belongs to exactly one pantry; nobody else is tied to one.
        CheckConstraint(
            "(role = 'pantry_manager') = (pantry_id IS NOT NULL)", name="pantry_only_for_managers"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    pantry_id: Mapped[int | None] = mapped_column(ForeignKey("pantries.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    # Raised to sign the user out everywhere (see app/auth/tokens.py).
    token_version: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Changing these makes every token issued before the change stop working.
REVOKING_FIELDS = ("is_active", "role", "pantry_id", "password_hash")


@event.listens_for(User, "before_update")
def _revoke_tokens_on_sensitive_change(_mapper, _connection, user: User) -> None:
    changed_version = attributes.get_history(user, "token_version").has_changes()
    if not changed_version and any(
        attributes.get_history(user, field).has_changes() for field in REVOKING_FIELDS
    ):
        user.token_version = (user.token_version or 0) + 1


class RateLimit(Base):
    """A request counter for one user and endpoint in a one-hour window (hashed key)."""

    __tablename__ = "rate_limits"
    __table_args__ = (CheckConstraint("count >= 0", name="count_nonneg"),)

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer)


class LoginThrottle(Base):
    """Failed login attempts, per email and per address (stored as hashes, never as the values).
    Lives in the database so every API instance sees the same counts."""

    __tablename__ = "login_throttle"
    __table_args__ = (CheckConstraint("failures >= 0", name="failures_nonneg"),)

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer)
    first_failure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
