"""The weekly job: train the forward forecast, then rerun allocation against it."""

from __future__ import annotations

import logging
import time
from datetime import date

from sqlalchemy.orm import Session

from app.ai.llm_provider import LLMProvider
from app.errors import ApiError
from app.services import allocation_runs, forecast_runs, retention
from app.storage import StorageBackend

logger = logging.getLogger("pantrypulse.refresh")


def run_weekly_refresh(
    db: Session,
    *,
    storage: StorageBackend,
    forecast_config,
    llm: LLMProvider,
    user_id: int,
    today: date,
    raw_retention_days: int = retention.RETENTION_DAYS,
) -> dict:
    steps = []
    started = time.monotonic()
    forecast = forecast_runs.run_forward_checked(db, storage, forecast_config, user_id)
    steps.append(
        {"name": "forecast", "status": "done", "seconds": round(time.monotonic() - started, 1)}
    )
    mark = time.monotonic()
    try:
        allocation = allocation_runs.run_allocation(db, llm, user_id, today)
    except ApiError as exc:
        # The new forecast is already saved; say so rather than hiding it.
        raise ApiError(
            exc.status_code,
            "refresh_partial",
            f"The forecast was saved, but the allocation failed: {exc.message}",
            {"forecast_run_id": forecast.id, "cause": exc.code},
        ) from exc
    steps.append(
        {"name": "allocation", "status": "done", "seconds": round(time.monotonic() - mark, 1)}
    )
    cleared = retention.clear_old_raw_output(db, today, raw_retention_days)
    db.commit()
    logger.info(
        "weekly_refresh",
        extra={"forecast_run_id": forecast.id, "allocation_run_id": allocation.id,
               "seconds": round(time.monotonic() - started, 1)},
    )  # fmt: skip
    return {
        "steps": steps,
        "forecast_run_id": forecast.id,
        "allocation_run_id": allocation.id,
        "week_start": allocation.week_start,
        "raw_outputs_cleared": cleared,
        "proposed_rows": allocation.reasons_ai + allocation.reasons_template,
        "total_seconds": round(time.monotonic() - started, 1),
    }
