from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import RUN_STATUSES
from app.models.base import MONDAY_CHECK, Base, in_list


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (
        CheckConstraint(in_list("status", RUN_STATUSES), name="status_valid"),
        CheckConstraint("wape_lightgbm IS NULL OR wape_lightgbm >= 0", name="wape_lgbm_nonneg"),
        CheckConstraint("wape_baseline IS NULL OR wape_baseline >= 0", name="wape_base_nonneg"),
        CheckConstraint("train_start <= train_end", name="train_window_ordered"),
        CheckConstraint(MONDAY_CHECK.format(col="horizon_week_start"), name="horizon_is_monday"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(60))
    wape_lightgbm: Mapped[float | None] = mapped_column(Numeric(7, 4))
    wape_baseline: Mapped[float | None] = mapped_column(Numeric(7, 4))
    train_start: Mapped[date] = mapped_column(Date)
    train_end: Mapped[date] = mapped_column(Date)
    horizon_week_start: Mapped[date] = mapped_column(Date)  # first week that was forecast
    status: Mapped[str] = mapped_column(String(20))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint("forecast_run_id", "pantry_id", "category_id", "week_start"),
        CheckConstraint(MONDAY_CHECK.format(col="week_start"), name="week_is_monday"),
        CheckConstraint("p10_lbs >= 0", name="p10_nonneg"),
        CheckConstraint("p10_lbs <= p50_lbs AND p50_lbs <= p90_lbs", name="quantiles_ordered"),
        CheckConstraint("baseline_lbs IS NULL OR baseline_lbs >= 0", name="baseline_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"))
    pantry_id: Mapped[int] = mapped_column(ForeignKey("pantries.id", ondelete="RESTRICT"))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    week_start: Mapped[date] = mapped_column(Date)
    p10_lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    p50_lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    p90_lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    baseline_lbs: Mapped[float | None] = mapped_column(Numeric(12, 2))  # seasonal-naive forecast
