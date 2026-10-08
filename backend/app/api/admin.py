from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db, require_admin
from app.jobs.weekly_refresh import run_weekly_refresh
from app.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


class StepOut(BaseModel):
    name: str
    status: str
    seconds: float


class RefreshOut(BaseModel):
    steps: list[StepOut]
    forecast_run_id: int
    allocation_run_id: int
    week_start: date
    proposed_rows: int
    total_seconds: float


@router.post("/jobs/weekly-refresh", response_model=RefreshOut)
def weekly_refresh(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Train the forward forecast, then rerun allocation against it."""
    state = request.app.state
    return run_weekly_refresh(
        db,
        storage=state.storage,
        forecast_config=state.forecast_config,
        llm=state.llm,
        user_id=user.id,
        today=state.today(),
    )
