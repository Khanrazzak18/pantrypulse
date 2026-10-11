from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db, require_coordinator
from app.constants import WAREHOUSE
from app.models import (
    Allocation,
    AllocationRun,
    Category,
    DonationItem,
    InventoryLot,
    Pantry,
    User,
)
from app.schemas.allocations import (
    AllocationList,
    AllocationOut,
    AllocationRunOut,
    AllocationSummary,
    BulkApproveIn,
    BulkApproveOut,
    EditIn,
    LatestAllocationRun,
    LotRef,
    PantryRef,
)
from app.schemas.types import PathId, SafeDate
from app.services import allocation_runs as svc
from app.services.optimizer import haversine_miles

router = APIRouter(
    prefix="/api/allocations", tags=["allocations"], dependencies=[Depends(require_coordinator)]
)


def _today(request: Request) -> date:
    return request.app.state.today()


def run_out(db: Session, run: AllocationRun) -> AllocationRunOut:
    rows = db.scalar(
        select(func.count()).select_from(Allocation).where(Allocation.allocation_run_id == run.id)
    )
    return AllocationRunOut(
        id=run.id,
        status=run.status,
        forecast_run_id=run.forecast_run_id,
        week_start=run.week_start,
        delivery_date=run.delivery_date,
        created_at=run.created_at,
        lots_considered=run.lots_considered,
        lots_excluded=run.lots_excluded,
        shipped_lbs=float(run.shipped_lbs),
        rows=rows or 0,
        reasons_ai=run.reasons_ai,
        reasons_template=run.reasons_template,
        reason_model_id=run.reason_model_id,
        duration_ms=run.duration_ms,
    )


def rows_out(db: Session, ids: list[int] | None, week: date | None, today: date, status=None):
    delivery = svc.planned_delivery(week, today) if week else today
    query = (
        select(Allocation, Pantry, InventoryLot, DonationItem.name, Category.name)
        .join(Pantry, Pantry.id == Allocation.pantry_id)
        .join(InventoryLot, InventoryLot.id == Allocation.lot_id)
        .join(DonationItem, DonationItem.id == InventoryLot.donation_item_id)
        .join(Category, Category.id == InventoryLot.category_id)
        .join(AllocationRun, AllocationRun.id == Allocation.allocation_run_id)
        .order_by(Pantry.name, Allocation.recommended_lbs.desc(), Allocation.id)
    )
    if ids is not None:
        query = query.where(Allocation.id.in_(ids))
    if week is not None:
        query = query.where(AllocationRun.week_start == week)
    if status is not None:
        query = query.where(Allocation.status == status)
    out = []
    for a, p, lot, item_name, category in db.execute(query):
        out.append(
            AllocationOut(
                id=a.id,
                run_id=a.allocation_run_id,
                status=a.status,
                recommended_lbs=float(a.recommended_lbs),
                final_lbs=float(a.final_lbs) if a.final_lbs is not None else None,
                delivery_date=a.delivery_date,
                reason=a.reason,
                reason_source=a.reason_source,
                pantry=PantryRef(
                    id=p.id,
                    name=p.name,
                    county=p.county,
                    miles=round(
                        haversine_miles(*WAREHOUSE, float(p.latitude), float(p.longitude)), 1
                    ),
                ),
                lot=LotRef(
                    id=lot.id,
                    item_name=item_name,
                    category=category,
                    storage_type=lot.storage_type,
                    expiry_date=lot.expiry_date,
                    remaining_lbs=float(lot.remaining_lbs),
                    days_left=None
                    if lot.expiry_date is None
                    else max(0, (lot.expiry_date - delivery).days),
                ),
                decided_at=a.decided_at,
            )
        )
    return out


def _latest_run(db: Session) -> AllocationRun | None:
    return db.scalar(
        select(AllocationRun).order_by(AllocationRun.created_at.desc(), AllocationRun.id.desc())
    )


@router.post("/run", status_code=201, response_model=AllocationRunOut)
def run_allocation(
    request: Request, user: User = Depends(require_coordinator), db: Session = Depends(get_db)
) -> AllocationRunOut:
    """Propose who gets which lot this week. Re-running replaces proposals nobody has decided."""
    run = svc.run_allocation(db, request.app.state.llm, user.id, _today(request))
    return run_out(db, run)


@router.get("/runs/latest", response_model=LatestAllocationRun)
def latest_run(db: Session = Depends(get_db)) -> LatestAllocationRun:
    run = _latest_run(db)
    return LatestAllocationRun(run=run_out(db, run) if run else None)


@router.post("/runs/{run_id}/reasons", response_model=AllocationRunOut)
def more_reasons(
    run_id: PathId, request: Request, db: Session = Depends(get_db)
) -> AllocationRunOut:
    run = svc.write_more_reasons(db, request.app.state.llm, run_id, _today(request))
    return run_out(db, run)


@router.get("", response_model=AllocationList)
def list_allocations(
    request: Request,
    status: str | None = Query(default=None, pattern="^(proposed|approved|edited|rejected)$"),
    week_start: SafeDate | None = None,
    db: Session = Depends(get_db),
) -> AllocationList:
    run = _latest_run(db)
    week = week_start or (run.week_start if run else None)
    empty = AllocationSummary(
        proposed=0, approved=0, edited=0, rejected=0, proposed_lbs=0, approved_lbs=0
    )
    if week is None:
        return AllocationList(run=None, week_start=None, rows=[], summary=empty)
    rows = rows_out(db, None, week, _today(request), status)
    everything = rows if status is None else rows_out(db, None, week, _today(request))
    counts = {s: sum(1 for r in everything if r.status == s) for s in svc_statuses()}
    summary = AllocationSummary(
        **counts,
        proposed_lbs=round(sum(r.recommended_lbs for r in everything if r.status == "proposed"), 2),
        approved_lbs=round(sum(r.final_lbs or 0 for r in everything if r.status in svc.DECIDED), 2),
    )
    return AllocationList(
        run=run_out(db, run) if run and run.week_start == week else None,
        week_start=week,
        rows=rows,
        summary=summary,
    )


def svc_statuses():
    return ("proposed", "approved", "edited", "rejected")


def _one(db: Session, allocation_id: int, today: date) -> AllocationOut:
    run_week = db.scalar(
        select(AllocationRun.week_start)
        .join(Allocation, Allocation.allocation_run_id == AllocationRun.id)
        .where(Allocation.id == allocation_id)
    )
    return rows_out(db, [allocation_id], run_week, today)[0]


@router.post("/bulk-approve", response_model=BulkApproveOut)
def bulk_approve(
    body: BulkApproveIn,
    request: Request,
    user: User = Depends(require_coordinator),
    db: Session = Depends(get_db),
) -> BulkApproveOut:
    rows = svc.bulk_approve(db, body.ids, user.id, _today(request))
    return BulkApproveOut(
        approved=len(rows), approved_lbs=round(sum(float(r.final_lbs) for r in rows), 2)
    )


@router.post("/{allocation_id}/approve", response_model=AllocationOut)
def approve(
    allocation_id: PathId,
    request: Request,
    user: User = Depends(require_coordinator),
    db: Session = Depends(get_db),
) -> AllocationOut:
    svc.approve(db, allocation_id, user.id, _today(request))
    return _one(db, allocation_id, _today(request))


@router.post("/{allocation_id}/edit", response_model=AllocationOut)
def edit(
    allocation_id: PathId,
    body: EditIn,
    request: Request,
    user: User = Depends(require_coordinator),
    db: Session = Depends(get_db),
) -> AllocationOut:
    svc.edit(db, allocation_id, body.lbs, body.note, user.id, _today(request))
    return _one(db, allocation_id, _today(request))


@router.post("/{allocation_id}/reject", response_model=AllocationOut)
def reject(
    allocation_id: PathId,
    request: Request,
    user: User = Depends(require_coordinator),
    db: Session = Depends(get_db),
) -> AllocationOut:
    svc.reject(db, allocation_id, user.id)
    return _one(db, allocation_id, _today(request))
