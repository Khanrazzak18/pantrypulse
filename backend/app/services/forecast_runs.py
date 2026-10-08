"""Saving forecasts: reading the panel from the database, recording runs, storing models."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from app.models import Forecast, ForecastRun
from app.services import forecasting as fc
from app.storage import StorageBackend

logger = logging.getLogger("pantrypulse.forecast")

# A "running" row older than this is treated as a crashed run and no longer blocks new ones.
STALE_AFTER = timedelta(minutes=10)
INSERT_CHUNK = 5_000
MODEL_FILES = ("p10.txt", "p50.txt", "p90.txt", "meta.json")

PANEL_SQL = text(
    """
    SELECT d.pantry_id, d.category_id, d.week_start,
           d.lbs::float8 AS lbs, d.households::float8 AS households,
           s.severity::float8 AS severity, s.households_turned_away::float8 AS turned_away,
           p.county, p.baseline_households,
           w.avg_temp_f::float8 AS temp, w.precip_in::float8 AS precip,
           w.school_holiday, w.benefit_week
    FROM distributions d
    JOIN pantries p ON p.id = d.pantry_id
    LEFT JOIN shortage_reports s
           ON s.pantry_id = d.pantry_id AND s.category_id = d.category_id
          AND s.week_start = d.week_start
    LEFT JOIN weekly_context w ON w.county = p.county AND w.week_start = d.week_start
    ORDER BY d.pantry_id, d.category_id, d.week_start
    """
)


class RunInProgress(Exception):
    """Another forecast run started recently and has not finished."""


class ForecastFailed(Exception):
    """The model could not be built. The run is recorded as failed with the reason."""


def load_panel(db: Session) -> pd.DataFrame:
    """Everything the forecast learns from: one row per pantry, category and week."""
    panel = pd.read_sql(PANEL_SQL, db.connection())
    panel["week_start"] = pd.to_datetime(panel["week_start"])
    return panel


def _insert_forecasts(db: Session, run_id: int, predictions: pd.DataFrame) -> int:
    def number(value):
        return None if pd.isna(value) else round(float(value), 2)

    rows = [
        {
            "forecast_run_id": run_id,
            "pantry_id": int(r.pantry_id),
            "category_id": int(r.category_id),
            "week_start": r.week_start.date() if hasattr(r.week_start, "date") else r.week_start,
            "p10_lbs": number(r.p10),
            "p50_lbs": number(r.p50),
            "p90_lbs": number(r.p90),
            "baseline_lbs": number(r.baseline_lbs),
        }
        for r in predictions.itertuples(index=False)
    ]
    for start in range(0, len(rows), INSERT_CHUNK):
        db.execute(insert(Forecast), rows[start : start + INSERT_CHUNK])
    return len(rows)


def _discard_model_files(storage: StorageBackend, prefix: str) -> None:
    for name in MODEL_FILES:
        try:
            storage.delete(f"{prefix}/{name}")
        except Exception:  # best effort: the run is already being marked failed
            logger.warning("could not remove %s/%s", prefix, name)


def run_forward(
    db: Session, storage: StorageBackend, config: fc.ForecastConfig, user_id: int | None
) -> ForecastRun:
    """Train once on all history, write next week's forecast, and record the run."""
    cutoff = datetime.now(UTC) - STALE_AFTER
    running = db.scalar(
        select(func.count())
        .select_from(ForecastRun)
        .where(ForecastRun.status == "running", ForecastRun.created_at > cutoff)
    )
    if running:
        raise RunInProgress("A forecast is already being built.")

    panel = load_panel(db)
    found = int(panel["week_start"].nunique()) if len(panel) else 0
    if found < config.min_history_weeks:
        raise fc.NotEnoughHistory(found, config.min_history_weeks)

    last = panel["week_start"].max()
    run = ForecastRun(
        model_name="lightgbm",
        kind="forward",
        status="running",
        train_start=panel["week_start"].min().date(),
        train_end=last.date(),
        horizon_week_start=(last + pd.Timedelta(weeks=1)).date(),
        created_by=user_id,
    )
    db.add(run)
    db.commit()  # visible straight away, so a second request (or a crash) can be seen
    run_id = run.id
    prefix = f"forecasts/run-{run_id}"
    started = time.perf_counter()
    try:
        result = fc.forward_forecast(panel, config)
        fc.save_models(storage, prefix, result.models)
        written = _insert_forecasts(
            db, run_id, result.predictions.assign(week_start=pd.Timestamp(result.week_start))
        )
        run = db.get(ForecastRun, run_id)
        run.status = "completed"
        run.model_key = prefix
        run.train_start, run.train_end = result.models.train_start, result.models.train_end
        db.commit()
    except Exception as exc:
        db.rollback()
        _discard_model_files(storage, prefix)
        run = db.get(ForecastRun, run_id)
        run.status = "failed"
        run.error_message = f"{type(exc).__name__}: {exc}"[:1000]
        db.commit()
        logger.exception("forecast_failed", extra={"run_id": run_id})
        raise ForecastFailed(str(exc)) from exc
    logger.info(
        "forecast_run",
        extra={
            "run_id": run_id,
            "kind": "forward",
            "rows": written,
            "train_rows": result.models.train_rows,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    db.refresh(run)
    return run


def save_backtest(
    db: Session, storage: StorageBackend, result: fc.BacktestResult, panel: pd.DataFrame
) -> ForecastRun:
    """Record a finished backtest: its metrics on the run, every forecast it made, and the
    models from its last origin."""
    summary = fc.summarize_backtest(result.predictions)
    first_origin = result.folds[0].origin
    run = ForecastRun(
        model_name="lightgbm",
        kind="backtest",
        status="running",
        train_start=panel["week_start"].min().date(),
        train_end=result.folds[-1].train_end,
        horizon_week_start=first_origin,
        backtest_start=first_origin,
        created_by=None,
    )
    db.add(run)
    db.flush()
    prefix = f"forecasts/run-{run.id}"
    try:
        fc.save_models(storage, prefix, result.models)
        _insert_forecasts(db, run.id, result.predictions)
        run.wape_lightgbm = round(summary["wape_lightgbm"], 4)
        run.wape_baseline = round(summary["wape_baseline"], 4)
        run.coverage_p10_p90 = round(summary["coverage_p10_p90"], 4)
        run.model_key = prefix
        run.status = "completed"
        db.commit()
    except Exception:
        db.rollback()
        _discard_model_files(storage, prefix)
        raise
    db.refresh(run)
    return run


def latest_run(db: Session, kind: str) -> ForecastRun | None:
    return db.scalar(
        select(ForecastRun)
        .where(ForecastRun.kind == kind, ForecastRun.status == "completed")
        .order_by(ForecastRun.created_at.desc(), ForecastRun.id.desc())
        .limit(1)
    )


def run_forward_checked(db: Session, storage: StorageBackend, config, user_id: int) -> ForecastRun:
    """`run_forward`, with each expected failure turned into the API's error response."""
    from app.errors import ApiError

    try:
        return run_forward(db, storage, config, user_id)
    except fc.NotEnoughHistory as exc:
        raise ApiError(
            422,
            "not_enough_history",
            f"There isn't enough history to forecast yet: need at least {exc.needed} weeks, "
            f"found {exc.found}.",
            {"found": exc.found, "needed": exc.needed},
        ) from exc
    except RunInProgress as exc:
        raise ApiError(
            409,
            "forecast_in_progress",
            "A forecast is already being built. Wait a moment and refresh.",
        ) from exc
    except ForecastFailed as exc:
        raise ApiError(
            500,
            "forecast_failed",
            "The forecast could not be built. Please try again; if it keeps failing, ask an "
            "administrator to check the logs.",
        ) from exc
