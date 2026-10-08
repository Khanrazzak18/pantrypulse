from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import RUN_KINDS, RUN_STATUSES
from app.models.base import MONDAY_CHECK, Base, in_list


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (
        CheckConstraint(in_list("status", RUN_STATUSES), name="status_valid"),
        CheckConstraint("wape_lightgbm IS NULL OR wape_lightgbm >= 0", name="wape_lgbm_nonneg"),
        CheckConstraint("wape_baseline IS NULL OR wape_baseline >= 0", name="wape_base_nonneg"),
        CheckConstraint("train_start <= train_end", name="train_window_ordered"),
        CheckConstraint(MONDAY_CHECK.format(col="horizon_week_start"), name="horizon_is_monday"),
        CheckConstraint(in_list("kind", RUN_KINDS), name="kind_valid"),
        CheckConstraint(
            "coverage_p10_p90 IS NULL OR coverage_p10_p90 BETWEEN 0 AND 1", name="coverage_range"
        ),
        CheckConstraint(
            "backtest_start IS NULL OR " + MONDAY_CHECK.format(col="backtest_start"),
            name="backtest_start_is_monday",
        ),
        # A finished backtest always carries its metrics: that is what the Forecasts page shows.
        CheckConstraint(
            "kind <> 'backtest' OR status <> 'completed' OR (wape_lightgbm IS NOT NULL "
            "AND wape_baseline IS NOT NULL AND coverage_p10_p90 IS NOT NULL "
            "AND backtest_start IS NOT NULL)",
            name="backtest_has_metrics",
        ),
        CheckConstraint(
            "status <> 'failed' OR error_message IS NOT NULL", name="failed_has_reason"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(60))
    wape_lightgbm: Mapped[float | None] = mapped_column(Numeric(7, 4))
    wape_baseline: Mapped[float | None] = mapped_column(Numeric(7, 4))
    train_start: Mapped[date] = mapped_column(Date)
    train_end: Mapped[date] = mapped_column(Date)
    horizon_week_start: Mapped[date] = mapped_column(Date)  # first week that was forecast
    status: Mapped[str] = mapped_column(String(20))
    # forward = trained on all history to forecast next week; backtest = 12 rolling origins
    kind: Mapped[str] = mapped_column(String(20), server_default="forward")
    coverage_p10_p90: Mapped[float | None] = mapped_column(Numeric(5, 4))
    backtest_start: Mapped[date | None] = mapped_column(Date)  # first week that was scored
    model_key: Mapped[str | None] = mapped_column(String(300))  # where the model files live
    error_message: Mapped[str | None] = mapped_column(Text)
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
