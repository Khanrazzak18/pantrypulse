from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import MONDAY_CHECK, Base


class Distribution(Base):
    """Pounds a pantry handed out in a category and week. `households` is the number of
    households the pantry served that week (the same on every category row of that week)."""

    __tablename__ = "distributions"
    __table_args__ = (
        UniqueConstraint("pantry_id", "category_id", "week_start"),
        CheckConstraint(MONDAY_CHECK.format(col="week_start"), name="week_is_monday"),
        CheckConstraint("lbs >= 0", name="lbs_nonneg"),
        CheckConstraint("households >= 0", name="households_nonneg"),
        Index("ix_distributions_week_start", "week_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pantry_id: Mapped[int] = mapped_column(ForeignKey("pantries.id", ondelete="RESTRICT"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    week_start: Mapped[date] = mapped_column(Date)
    lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    households: Mapped[int] = mapped_column(Integer)


class ShortageReport(Base):
    """A pantry ran short of a category in a week. One row per pantry, category and week."""

    __tablename__ = "shortage_reports"
    __table_args__ = (
        UniqueConstraint("pantry_id", "category_id", "week_start"),
        CheckConstraint(MONDAY_CHECK.format(col="week_start"), name="week_is_monday"),
        CheckConstraint("severity BETWEEN 1 AND 3", name="severity_range"),
        CheckConstraint("households_turned_away >= 0", name="turned_away_nonneg"),
        Index("ix_shortage_reports_week_start", "week_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pantry_id: Mapped[int] = mapped_column(ForeignKey("pantries.id", ondelete="RESTRICT"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    week_start: Mapped[date] = mapped_column(Date)
    severity: Mapped[int] = mapped_column(SmallInteger)  # 1 minor, 2 serious, 3 ran out
    households_turned_away: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    reported_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
