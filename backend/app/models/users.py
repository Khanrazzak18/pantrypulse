from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func, true
from sqlalchemy.orm import Mapped, mapped_column

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
