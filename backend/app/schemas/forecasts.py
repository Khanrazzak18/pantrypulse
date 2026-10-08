from datetime import date, datetime

from pydantic import BaseModel


class ForecastRunOut(BaseModel):
    id: int
    kind: str  # forward | backtest
    status: str
    model_name: str
    created_at: datetime
    train_start: date
    train_end: date
    horizon_week_start: date
    backtest_start: date | None
    backtest_end: date | None  # last week that was forecast and scored
    wape_lightgbm: float | None
    wape_baseline: float | None
    coverage_p10_p90: float | None
    rows: int
    error_message: str | None


class LatestRuns(BaseModel):
    backtest: ForecastRunOut | None
    forward: ForecastRunOut | None


class ForecastRowOut(BaseModel):
    run_id: int
    pantry_id: int
    pantry_name: str
    category: str
    week_start: date
    p10_lbs: float
    p50_lbs: float
    p90_lbs: float
    baseline_lbs: float | None
    actual_lbs: float | None  # filled in once the week has happened


class SeriesPoint(BaseModel):
    week_start: date
    actual_lbs: float | None
    p10_lbs: float | None
    p50_lbs: float | None
    p90_lbs: float | None
    baseline_lbs: float | None
    source: str | None  # backtest | forward | None (history only)


class SeriesAccuracy(BaseModel):
    wape_lightgbm: float | None
    wape_baseline: float | None
    weeks_scored: int


class ForecastSeries(BaseModel):
    pantry_id: int
    pantry_name: str
    category: str
    points: list[SeriesPoint]
    accuracy: SeriesAccuracy | None
    backtest_run_id: int | None
    forward_run_id: int | None
