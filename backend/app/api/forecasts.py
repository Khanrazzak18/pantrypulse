from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db, require_coordinator
from app.constants import CATEGORY_NAMES
from app.errors import ApiError
from app.models import Category, Distribution, Forecast, ForecastRun, Pantry, User
from app.schemas.forecasts import (
    ForecastRowOut,
    ForecastRunOut,
    ForecastSeries,
    LatestRuns,
    SeriesAccuracy,
    SeriesPoint,
)
from app.schemas.types import PositiveId, SafeDate
from app.services import forecast_runs, forecasting

router = APIRouter(prefix="/api/forecasts", tags=["forecasts"])
CategoryName = Literal[*CATEGORY_NAMES]


def run_out(db: Session, run: ForecastRun) -> ForecastRunOut:
    rows = db.scalar(
        select(func.count()).select_from(Forecast).where(Forecast.forecast_run_id == run.id)
    )
    return ForecastRunOut(
        id=run.id,
        kind=run.kind,
        status=run.status,
        model_name=run.model_name,
        created_at=run.created_at,
        train_start=run.train_start,
        train_end=run.train_end,
        horizon_week_start=run.horizon_week_start,
        backtest_start=run.backtest_start,
        # the model of the last origin trained through the week before the last week scored
        backtest_end=run.train_end + timedelta(weeks=1) if run.kind == "backtest" else None,
        wape_lightgbm=float(run.wape_lightgbm) if run.wape_lightgbm is not None else None,
        wape_baseline=float(run.wape_baseline) if run.wape_baseline is not None else None,
        coverage_p10_p90=float(run.coverage_p10_p90) if run.coverage_p10_p90 is not None else None,
        rows=rows or 0,
        error_message=run.error_message,
    )


@router.post("/run", status_code=201, response_model=ForecastRunOut)
def run_forecast(
    request: Request, user: User = Depends(require_coordinator), db: Session = Depends(get_db)
) -> ForecastRunOut:
    """Train once on all history and save next week's forecast. Takes a few seconds; the slow
    12-week backtest is a separate command (`make backtest`)."""
    run = forecast_runs.run_forward_checked(
        db, request.app.state.storage, request.app.state.forecast_config, user.id
    )
    return run_out(db, run)


@router.get("/runs/latest", response_model=LatestRuns, dependencies=[Depends(require_coordinator)])
def latest_runs(db: Session = Depends(get_db)) -> LatestRuns:
    backtest = forecast_runs.latest_run(db, "backtest")
    forward = forecast_runs.latest_run(db, "forward")
    return LatestRuns(
        backtest=run_out(db, backtest) if backtest else None,
        forward=run_out(db, forward) if forward else None,
    )


@router.get("", response_model=list[ForecastRowOut], dependencies=[Depends(require_coordinator)])
def list_forecasts(
    pantry_id: PositiveId | None = None,
    category: CategoryName | None = None,
    week_start: SafeDate | None = None,
    kind: Literal["forward", "backtest"] = "forward",
    run_id: PositiveId | None = None,
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[ForecastRowOut]:
    if week_start is not None and week_start.isoweekday() != 1:
        raise ApiError(
            422,
            "validation_error",
            "Some fields are invalid.",
            [
                {
                    "field": "week_start",
                    "message": "week_start must be a Monday.",
                    "type": "value_error",
                }
            ],
        )
    if run_id is not None:
        run = db.get(ForecastRun, run_id)
        if run is None:
            raise ApiError(404, "not_found", "Forecast run not found.")
    else:
        run = forecast_runs.latest_run(db, kind)
        if run is None:
            return []

    query = (
        select(Forecast, Pantry.name, Category.name, Distribution.lbs)
        .join(Pantry, Pantry.id == Forecast.pantry_id)
        .join(Category, Category.id == Forecast.category_id)
        .outerjoin(
            Distribution,
            (Distribution.pantry_id == Forecast.pantry_id)
            & (Distribution.category_id == Forecast.category_id)
            & (Distribution.week_start == Forecast.week_start),
        )
        .where(Forecast.forecast_run_id == run.id)
        .order_by(Forecast.week_start, Forecast.pantry_id, Category.id)
        .limit(limit)
    )
    if pantry_id is not None:
        query = query.where(Forecast.pantry_id == pantry_id)
    if category is not None:
        query = query.where(Category.name == category)
    if week_start is not None:
        query = query.where(Forecast.week_start == week_start)
    return [
        ForecastRowOut(
            run_id=f.forecast_run_id,
            pantry_id=f.pantry_id,
            pantry_name=pantry_name,
            category=category_name,
            week_start=f.week_start,
            p10_lbs=float(f.p10_lbs),
            p50_lbs=float(f.p50_lbs),
            p90_lbs=float(f.p90_lbs),
            baseline_lbs=float(f.baseline_lbs) if f.baseline_lbs is not None else None,
            actual_lbs=float(actual) if actual is not None else None,
        )
        for f, pantry_name, category_name, actual in db.execute(query)
    ]


@router.get("/series", response_model=ForecastSeries, dependencies=[Depends(require_coordinator)])
def forecast_series(
    pantry_id: PositiveId,
    category: CategoryName,
    history_weeks: int = Query(default=26, ge=4, le=104),
    db: Session = Depends(get_db),
) -> ForecastSeries:
    """Everything the chart needs for one pantry and category: recent actuals, the backtest
    forecasts for the weeks that have happened, and next week's forecast."""
    pantry = db.get(Pantry, pantry_id)
    if pantry is None:
        raise ApiError(404, "not_found", "Pantry not found.")
    category_id = db.scalar(select(Category.id).where(Category.name == category))

    last_week = db.scalar(select(func.max(Distribution.week_start)))
    actual: dict[date, float] = {}
    if last_week is not None:
        start = last_week - timedelta(weeks=history_weeks - 1)
        actual = {
            week: float(lbs)
            for week, lbs in db.execute(
                select(Distribution.week_start, Distribution.lbs).where(
                    Distribution.pantry_id == pantry_id,
                    Distribution.category_id == category_id,
                    Distribution.week_start >= start,
                )
            )
        }
    all_actual = {
        week: float(lbs)
        for week, lbs in db.execute(
            select(Distribution.week_start, Distribution.lbs).where(
                Distribution.pantry_id == pantry_id, Distribution.category_id == category_id
            )
        )
    }

    def rows_of(run: ForecastRun | None) -> dict[date, Forecast]:
        if run is None:
            return {}
        found = db.scalars(
            select(Forecast).where(
                Forecast.forecast_run_id == run.id,
                Forecast.pantry_id == pantry_id,
                Forecast.category_id == category_id,
            )
        )
        return {f.week_start: f for f in found}

    backtest_run = forecast_runs.latest_run(db, "backtest")
    forward_run = forecast_runs.latest_run(db, "forward")
    backtest, forward = rows_of(backtest_run), rows_of(forward_run)

    in_window = (
        {w for w in backtest if last_week is None or w >= start} if actual else set(backtest)
    )
    weeks = sorted(set(actual) | in_window | set(forward))
    points = []
    for week in weeks:
        forecast = forward.get(week) or backtest.get(week)
        points.append(
            SeriesPoint(
                week_start=week,
                actual_lbs=actual.get(week),
                p10_lbs=float(forecast.p10_lbs) if forecast else None,
                p50_lbs=float(forecast.p50_lbs) if forecast else None,
                p90_lbs=float(forecast.p90_lbs) if forecast else None,
                baseline_lbs=float(forecast.baseline_lbs)
                if forecast and forecast.baseline_lbs is not None
                else None,
                source="forward" if week in forward else "backtest" if week in backtest else None,
            )
        )

    accuracy = None
    scored = [(w, f) for w, f in sorted(backtest.items()) if w in all_actual]
    if scored:
        y = [all_actual[w] for w, _ in scored]
        accuracy = SeriesAccuracy(
            wape_lightgbm=forecasting.wape(y, [float(f.p50_lbs) for _, f in scored]),
            wape_baseline=forecasting.wape(
                y,
                [
                    float(f.baseline_lbs) if f.baseline_lbs is not None else float("nan")
                    for _, f in scored
                ],
            ),
            weeks_scored=len(scored),
        )
    return ForecastSeries(
        pantry_id=pantry_id,
        pantry_name=pantry.name,
        category=category,
        points=points,
        accuracy=accuracy,
        backtest_run_id=backtest_run.id if backtest_run else None,
        forward_run_id=forward_run.id if forward_run else None,
    )
