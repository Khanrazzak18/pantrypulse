from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from pydantic import AfterValidator
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db, require_admin
from app.models import MonthlySummary, User
from app.schemas.dashboard import (
    ApproveIn,
    MetricsOut,
    SummaryOut,
    SummaryResponse,
)
from app.schemas.types import SafeDate, check_month
from app.security.rate_limit import rate_limit
from app.services import dashboard, summaries

router = APIRouter(
    prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_admin)]
)
MonthPath = Annotated[
    str, Path(description="YYYY-MM, 2020-01 to 2100-12"), AfterValidator(check_month)
]


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
    start: SafeDate | None = None,
    end: SafeDate | None = None,
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
def get_summary(month: MonthPath, db: Session = Depends(get_db)) -> SummaryResponse:
    row = summaries.get(db, month)
    return SummaryResponse(summary=_summary_out(row) if row else None)


@router.post(
    "/summaries/{month}/draft",
    response_model=SummaryOut,
    status_code=201,
    dependencies=[Depends(rate_limit("summary_draft", require_admin))],
)
def draft_summary(request: Request, month: MonthPath, db: Session = Depends(get_db)) -> SummaryOut:
    return _summary_out(summaries.draft(db, request.app.state.llm, month))


@router.post("/summaries/{month}/approve", response_model=SummaryOut)
def approve_summary(
    body: ApproveIn,
    month: MonthPath,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SummaryOut:
    return _summary_out(summaries.approve(db, month, body.text, user.id))
