from datetime import date

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db, require_admin
from app.models import MonthlySummary, User
from app.schemas.dashboard import (
    ApproveIn,
    MetricsOut,
    SummaryOut,
    SummaryResponse,
)
from app.services import dashboard, summaries

router = APIRouter(
    prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_admin)]
)
Month = Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="YYYY-MM")


def _summary_out(row: MonthlySummary) -> SummaryOut:
    return SummaryOut(
        month=f"{row.month:%Y-%m}",
        status=row.status,
        aggregates=row.aggregates,
        ai_draft=row.ai_draft,
        final_text=row.final_text,
        model_id=row.model_id,
        approved_at=row.approved_at,
        created_at=row.created_at,
    )


@router.get("/metrics", response_model=MetricsOut)
def metrics(
    request: Request,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Spoilage, stockouts, pounds distributed and households served for a range of weeks."""
    first, last, data_start, data_end = dashboard.resolve_range(
        db, start, end, request.app.state.today()
    )
    out = dashboard.metrics(db, first, last)
    out["range"] = {"start": first, "end": last, "data_start": data_start, "data_end": data_end}
    return out


@router.get("/summaries/{month}", response_model=SummaryResponse)
def get_summary(month: str = Month, db: Session = Depends(get_db)) -> SummaryResponse:
    row = summaries.get(db, month)
    return SummaryResponse(summary=_summary_out(row) if row else None)


@router.post("/summaries/{month}/draft", response_model=SummaryOut, status_code=201)
def draft_summary(
    request: Request, month: str = Month, db: Session = Depends(get_db)
) -> SummaryOut:
    return _summary_out(summaries.draft(db, request.app.state.llm, month))


@router.post("/summaries/{month}/approve", response_model=SummaryOut)
def approve_summary(
    body: ApproveIn,
    month: str = Month,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SummaryOut:
    return _summary_out(summaries.approve(db, month, body.text, user.id))
