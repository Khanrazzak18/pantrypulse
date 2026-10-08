from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import CATEGORY_NAMES, COUNTIES
from app.models.base import MONDAY_CHECK, Base, in_list


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (CheckConstraint(in_list("name", CATEGORY_NAMES), name="name_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    perishable: Mapped[bool] = mapped_column(Boolean)


class Pantry(Base):
    __tablename__ = "pantries"
    __table_args__ = (
        CheckConstraint(in_list("county", COUNTIES), name="county_valid"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
        CheckConstraint("cold_capacity_lbs >= 0", name="cold_capacity_nonneg"),
        CheckConstraint("dry_capacity_lbs >= 0", name="dry_capacity_nonneg"),
        CheckConstraint("baseline_households > 0", name="households_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    county: Mapped[str] = mapped_column(String(40))
    latitude: Mapped[float] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float] = mapped_column(Numeric(9, 6))
    cold_capacity_lbs: Mapped[int] = mapped_column(Integer)
    dry_capacity_lbs: Mapped[int] = mapped_column(Integer)
    baseline_households: Mapped[int] = mapped_column(Integer)  # households served per month


class WeeklyContext(Base):
    """Per-county weekly features the forecast needs: weather, school holidays, benefit weeks."""

    __tablename__ = "weekly_context"
    __table_args__ = (
        UniqueConstraint("county", "week_start"),
        CheckConstraint(in_list("county", COUNTIES), name="county_valid"),
        CheckConstraint(MONDAY_CHECK.format(col="week_start"), name="week_is_monday"),
        CheckConstraint("precip_in >= 0", name="precip_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    county: Mapped[str] = mapped_column(String(40))
    week_start: Mapped[date] = mapped_column(Date)
    avg_temp_f: Mapped[float] = mapped_column(Numeric(5, 1))
    precip_in: Mapped[float] = mapped_column(Numeric(5, 2))
    school_holiday: Mapped[bool] = mapped_column(Boolean)
    benefit_week: Mapped[bool] = mapped_column(Boolean)
