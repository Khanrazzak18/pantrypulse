from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db, require_roles
from app.models import (
    Allocation,
    Category,
    DonationItem,
    InventoryLot,
    Pantry,
    ShortageReport,
    User,
)
from app.schemas.portal import (
    DeliveriesOut,
    DeliveryOut,
    ShortageReportIn,
    ShortageReportOut,
)
from app.services.dashboard import monday_of

router = APIRouter(prefix="/api/pantry", tags=["pantry portal"])
require_manager = require_roles("pantry_manager")
RECENT_DAYS = 7


@router.get("/deliveries", response_model=DeliveriesOut)
def deliveries(
    request: Request, user: User = Depends(require_manager), db: Session = Depends(get_db)
) -> DeliveriesOut:
    """Approved deliveries for the manager's own pantry: upcoming, and the last week's."""
    today = request.app.state.today()
    query = (
        select(Allocation, DonationItem.name, Category.name, InventoryLot.expiry_date)
        .join(InventoryLot, InventoryLot.id == Allocation.lot_id)
        .join(DonationItem, DonationItem.id == InventoryLot.donation_item_id)
        .join(Category, Category.id == InventoryLot.category_id)
        .where(
            Allocation.pantry_id == user.pantry_id,
            Allocation.status.in_(("approved", "edited")),
            Allocation.delivery_date >= today - timedelta(days=RECENT_DAYS),
        )
        .order_by(Allocation.delivery_date, Allocation.id)
    )
    upcoming: list[DeliveryOut] = []
    recent: list[DeliveryOut] = []
    for a, item_name, category, expiry in db.execute(query):
        row = DeliveryOut(
            id=a.id,
            category=category,
            item_name=item_name,
            final_lbs=float(a.final_lbs),
            delivery_date=a.delivery_date,
            expiry_date=expiry,
            edited=a.status == "edited",
        )
        (upcoming if a.delivery_date >= today else recent).append(row)
    recent.reverse()  # most recent first
    return DeliveriesOut(pantry=db.get(Pantry, user.pantry_id), upcoming=upcoming, recent=recent)


def _out(report: ShortageReport, category: str, updated: bool) -> ShortageReportOut:
    return ShortageReportOut(
        id=report.id,
        category=category,
        week_start=report.week_start,
        severity=report.severity,
        households_turned_away=report.households_turned_away,
        note=report.notes,
        updated=updated,
        updated_at=report.updated_at,
    )


@router.post("/shortage-reports", response_model=ShortageReportOut, status_code=201)
def report_shortage(
    body: ShortageReportIn,
    request: Request,
    response: Response,
    user: User = Depends(require_manager),
    db: Session = Depends(get_db),
) -> ShortageReportOut:
    """File a shortage for this week. A second report for the same category replaces the first."""
    week = monday_of(request.app.state.today())
    category_id = db.scalar(select(Category.id).where(Category.name == body.category))
    values = {
        "pantry_id": user.pantry_id,
        "category_id": category_id,
        "week_start": week,
        "severity": body.severity,
        "households_turned_away": body.households_turned_away,
        "notes": body.note,
        "reported_by": user.id,
    }
    stmt = insert(ShortageReport).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["pantry_id", "category_id", "week_start"],
        set_={**{k: stmt.excluded[k] for k in ("severity", "households_turned_away", "notes",
                                                "reported_by")},
              "updated_at": literal_column("now()")},
    ).returning(ShortageReport, literal_column("(xmax = 0)").label("inserted"))  # fmt: skip
    report, inserted = db.execute(stmt).one()
    db.commit()
    if not inserted:
        response.status_code = 200
    return _out(report, body.category, updated=not inserted)


@router.get("/shortage-reports", response_model=list[ShortageReportOut])
def this_weeks_reports(
    request: Request, user: User = Depends(require_manager), db: Session = Depends(get_db)
) -> list[ShortageReportOut]:
    week = monday_of(request.app.state.today())
    rows = db.execute(
        select(ShortageReport, Category.name)
        .join(Category, Category.id == ShortageReport.category_id)
        .where(ShortageReport.pantry_id == user.pantry_id, ShortageReport.week_start == week)
        .order_by(Category.id)
    )
    return [_out(r, name, updated=False) for r, name in rows]
