"""Running the optimizer for a forecast week, and recording what coordinators decide."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.ai.llm_provider import LLMProvider
from app.constants import WAREHOUSE
from app.errors import ApiError
from app.models import (
    Allocation,
    AllocationEdit,
    AllocationRun,
    Category,
    DonationItem,
    Forecast,
    InventoryLot,
    Pantry,
)
from app.services import forecast_runs, optimizer
from app.services.allocation_reasons import (
    ReasonFacts,
    template_reason,
    write_ai_reasons,
)

logger = logging.getLogger("pantrypulse.allocation")

DECIDED = ("approved", "edited")
ADVISORY_LOCK_KEY = 6_161_001  # one allocation run at a time


def planned_delivery(week_start: date, today: date) -> date:
    """Today if it is inside the forecast week, else the week's first day; never after Friday."""
    return min(max(week_start, today), week_start + timedelta(days=4))


def _lbs(value) -> float:
    return float(value)


# --- running ----------------------------------------------------------------------------------


def _inputs(db: Session, week: date, forecast_run_id: int):
    """Pantries, lots and demand for the week, net of what is already approved."""
    approved = db.execute(
        select(
            Allocation.pantry_id,
            InventoryLot.category_id,
            InventoryLot.storage_type,
            func.sum(Allocation.final_lbs),
        )
        .join(AllocationRun, AllocationRun.id == Allocation.allocation_run_id)
        .join(InventoryLot, InventoryLot.id == Allocation.lot_id)
        .where(AllocationRun.week_start == week, Allocation.status.in_(DECIDED))
        .group_by(Allocation.pantry_id, InventoryLot.category_id, InventoryLot.storage_type)
    )
    approved_cell: dict[tuple[int, int], float] = defaultdict(float)
    approved_cold: dict[int, float] = defaultdict(float)
    approved_dry: dict[int, float] = defaultdict(float)
    for pantry_id, category_id, storage, lbs in approved:
        approved_cell[pantry_id, category_id] += _lbs(lbs)
        (approved_dry if storage == "ambient" else approved_cold)[pantry_id] += _lbs(lbs)

    pantries = [
        optimizer.PantryIn(
            id=p.id,
            miles=optimizer.haversine_miles(*WAREHOUSE, float(p.latitude), float(p.longitude)),
            cold_capacity_lbs=max(0.0, p.cold_capacity_lbs - approved_cold[p.id]),
            dry_capacity_lbs=max(0.0, p.dry_capacity_lbs - approved_dry[p.id]),
        )
        for p in db.scalars(select(Pantry).order_by(Pantry.id))
    ]
    demand = {}
    for f in db.scalars(
        select(Forecast).where(
            Forecast.forecast_run_id == forecast_run_id, Forecast.week_start == week
        )
    ):
        done = approved_cell[f.pantry_id, f.category_id]
        p50, p90 = max(0.0, _lbs(f.p50_lbs) - done), max(0.0, _lbs(f.p90_lbs) - done)
        if p90 > 0:
            demand[f.pantry_id, f.category_id] = optimizer.DemandIn(p50=p50, p90=p90)
    lots = [
        optimizer.LotIn(
            id=lot.id,
            category_id=lot.category_id,
            storage_type=lot.storage_type,
            remaining_lbs=_lbs(lot.remaining_lbs),
            expiry_date=lot.expiry_date,
        )
        for lot in db.scalars(
            select(InventoryLot)
            .where(InventoryLot.status == "available", InventoryLot.remaining_lbs > 0)
            .order_by(InventoryLot.id)
        )
    ]
    return pantries, lots, demand


def run_allocation(db: Session, llm: LLMProvider, user_id: int, today: date) -> AllocationRun:
    started = time.monotonic()
    forecast_run = forecast_runs.latest_run(db, "forward")
    if forecast_run is None:
        raise ApiError(
            422,
            "no_forecast",
            "There is no forecast to allocate against yet. Run the forecast first.",
        )
    week = forecast_run.horizon_week_start
    delivery = planned_delivery(week, today)

    db.execute(select(func.pg_advisory_xact_lock(ADVISORY_LOCK_KEY)))
    # Re-running replaces what nobody has decided yet; decided rows stay as they are.
    stale = select(AllocationRun.id).where(AllocationRun.week_start == week)
    db.execute(
        delete(Allocation).where(
            Allocation.status == "proposed", Allocation.allocation_run_id.in_(stale)
        )
    )
    pantries, lots, demand = _inputs(db, week, forecast_run.id)
    if not lots:
        db.rollback()
        raise ApiError(
            422, "no_inventory", "There is no stock on hand to allocate. Confirm a donation first."
        )
    try:
        solution = optimizer.solve(lots, pantries, demand, delivery)
    except optimizer.OptimizerError as exc:
        db.rollback()
        logger.exception("optimizer_failed")
        raise ApiError(
            500, "optimizer_failed", "The allocation could not be calculated. Please try again."
        ) from exc

    run = AllocationRun(
        forecast_run_id=forecast_run.id,
        created_by=user_id,
        status="draft" if solution.shipments else "completed",
        week_start=week,
        delivery_date=delivery,
        lots_considered=len(lots) - len(solution.excluded_lot_ids),
        lots_excluded=len(solution.excluded_lot_ids),
        shipped_lbs=round(sum(s.lbs for s in solution.shipments), 2),
        reasons_ai=0,
        reasons_template=len(solution.shipments),
    )
    db.add(run)
    db.flush()

    facts = _facts_for(db, solution.shipments, demand, pantries, delivery)
    rows = []
    for s in solution.shipments:
        rows.append(
            Allocation(
                allocation_run_id=run.id,
                lot_id=s.lot_id,
                pantry_id=s.pantry_id,
                recommended_lbs=s.lbs,
                reason="",
                reason_source="template",
                status="proposed",
            )
        )
    db.add_all(rows)
    db.flush()
    reason_facts = []
    for row in rows:
        f = facts[row.lot_id, row.pantry_id]
        reason_facts.append(
            ReasonFacts(
                allocation_id=row.id,
                pantry_name=f["pantry_name"],
                county=f["county"],
                category=f["category"],
                lbs=_lbs(row.recommended_lbs),
                forecast_p50=f["p50"],
                miles=f["miles"],
                item_name=f["item_name"],
                days_left=f["days_left"],
            )
        )
        row.reason = template_reason(reason_facts[-1])
    run.duration_ms = int((time.monotonic() - started) * 1000)
    db.commit()  # proposals are visible before the (bounded) model call starts

    _apply_ai_reasons(db, llm, run, reason_facts)
    run.duration_ms = int((time.monotonic() - started) * 1000)
    db.commit()
    db.refresh(run)
    return run


def _facts_for(db, shipments, demand, pantries, delivery) -> dict:
    pantry_by_id = {p.id: p for p in db.scalars(select(Pantry))}
    miles = {p.id: p.miles for p in pantries}
    lots = {
        lot.id: (lot, name, category)
        for lot, name, category in db.execute(
            select(InventoryLot, DonationItem.name, Category.name)
            .join(DonationItem, DonationItem.id == InventoryLot.donation_item_id)
            .join(Category, Category.id == InventoryLot.category_id)
            .where(InventoryLot.id.in_({s.lot_id for s in shipments}))
        )
    }
    out = {}
    for s in shipments:
        lot, item_name, category = lots[s.lot_id]
        want = demand.get((s.pantry_id, lot.category_id))
        out[s.lot_id, s.pantry_id] = {
            "pantry_name": pantry_by_id[s.pantry_id].name,
            "county": pantry_by_id[s.pantry_id].county,
            "category": category,
            "p50": want.p50 if want else 0.0,
            "miles": miles[s.pantry_id],
            "item_name": item_name,
            "days_left": None
            if lot.expiry_date is None
            else max(0, (lot.expiry_date - delivery).days),
        }
    return out


def _apply_ai_reasons(db: Session, llm: LLMProvider, run: AllocationRun, facts: list) -> None:
    if not facts:
        return
    result = write_ai_reasons(llm, facts)
    run.reason_model_id = result.model_id
    run.input_tokens = (run.input_tokens or 0) + result.input_tokens
    run.output_tokens = (run.output_tokens or 0) + result.output_tokens
    for allocation_id, reason in result.reasons.items():
        db.execute(
            update(Allocation)
            .where(Allocation.id == allocation_id, Allocation.status == "proposed")
            .values(reason=reason, reason_source="ai")
        )
    db.flush()
    _recount_reasons(db, run)
    logger.info(
        "allocation_reasons",
        extra={
            "run_id": run.id,
            "ai": run.reasons_ai,
            "rejected": result.rejected,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "error": result.error,
        },
    )


def _recount_reasons(db: Session, run: AllocationRun) -> None:
    counts = dict(
        db.execute(
            select(Allocation.reason_source, func.count())
            .where(Allocation.allocation_run_id == run.id)
            .group_by(Allocation.reason_source)
        ).all()
    )
    run.reasons_ai = counts.get("ai", 0)
    run.reasons_template = counts.get("template", 0)


def write_more_reasons(db: Session, llm: LLMProvider, run_id: int, today: date) -> AllocationRun:
    """Ask the model for reasons on the largest rows that still have a template."""
    run = db.get(AllocationRun, run_id)
    if run is None:
        raise ApiError(404, "not_found", "Allocation run not found.")
    delivery = planned_delivery(run.week_start, today)
    rows = db.scalars(
        select(Allocation).where(
            Allocation.allocation_run_id == run.id,
            Allocation.status == "proposed",
            Allocation.reason_source == "template",
        )
    ).all()
    if not rows:
        return run
    forecast = {
        (f.pantry_id, f.category_id): _lbs(f.p50_lbs)
        for f in db.scalars(
            select(Forecast).where(
                Forecast.forecast_run_id == run.forecast_run_id,
                Forecast.week_start == run.week_start,
            )
        )
    }
    pantry_by_id = {p.id: p for p in db.scalars(select(Pantry))}
    lots = {
        lot.id: (lot, name, category)
        for lot, name, category in db.execute(
            select(InventoryLot, DonationItem.name, Category.name)
            .join(DonationItem, DonationItem.id == InventoryLot.donation_item_id)
            .join(Category, Category.id == InventoryLot.category_id)
            .where(InventoryLot.id.in_({r.lot_id for r in rows}))
        )
    }
    facts = []
    for r in rows:
        lot, item_name, category = lots[r.lot_id]
        p = pantry_by_id[r.pantry_id]
        facts.append(
            ReasonFacts(
                allocation_id=r.id,
                pantry_name=p.name,
                county=p.county,
                category=category,
                lbs=_lbs(r.recommended_lbs),
                forecast_p50=forecast.get((r.pantry_id, lot.category_id), 0.0),
                miles=optimizer.haversine_miles(*WAREHOUSE, float(p.latitude), float(p.longitude)),
                item_name=item_name,
                days_left=None
                if lot.expiry_date is None
                else max(0, (lot.expiry_date - delivery).days),
            )
        )
    _apply_ai_reasons(db, llm, run, facts)
    db.commit()
    db.refresh(run)
    return run


# --- deciding ---------------------------------------------------------------------------------


def _log(db, allocation_id, user_id, field, old, new) -> None:
    db.add(
        AllocationEdit(
            allocation_id=allocation_id,
            user_id=user_id,
            field=field,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
        )
    )


def _load_locked(db: Session, ids: list[int]) -> tuple[list[Allocation], dict[int, InventoryLot]]:
    """Lock the lots (in id order, so two requests cannot deadlock), then the rows."""
    found = db.scalars(select(Allocation).where(Allocation.id.in_(ids))).all()
    if len(found) != len(set(ids)):
        raise ApiError(404, "not_found", "Allocation not found.")
    lot_ids = sorted({a.lot_id for a in found})
    fresh = {"populate_existing": True}  # read what the locks protect, not earlier cached copies
    lots = {
        lot.id: lot
        for lot in db.scalars(
            select(InventoryLot)
            .where(InventoryLot.id.in_(lot_ids))
            .order_by(InventoryLot.id)
            .with_for_update()
            .execution_options(**fresh)
        )
    }
    rows = db.scalars(
        select(Allocation)
        .where(Allocation.id.in_(ids))
        .order_by(Allocation.id)
        .with_for_update()
        .execution_options(**fresh)
    ).all()
    return list(rows), lots


def _check_undecided(rows: list[Allocation]) -> None:
    decided = [a.id for a in rows if a.status != "proposed"]
    if decided:
        raise ApiError(
            409,
            "allocation_decided",
            "Someone already decided this allocation. Refresh to see the latest.",
            {"ids": decided},
        )


def _take_stock(
    db: Session,
    rows: list[Allocation],
    lots: dict[int, InventoryLot],
    amounts: dict[int, float],
    user_id: int,
    today: date,
    status: str,
) -> None:
    run_ids = {a.allocation_run_id for a in rows}
    runs = {r.id: r for r in db.scalars(select(AllocationRun).where(AllocationRun.id.in_(run_ids)))}
    needed: dict[int, float] = defaultdict(float)
    for a in rows:
        needed[a.lot_id] += amounts[a.id]
    for lot_id, lbs in needed.items():
        lot = lots[lot_id]
        week = runs[next(a for a in rows if a.lot_id == lot_id).allocation_run_id].week_start
        delivery = planned_delivery(week, today)
        if lot.expiry_date is not None and lot.expiry_date < delivery:
            raise ApiError(
                409,
                "lot_expired",
                "This food will have expired by its delivery date, so it can't be approved.",
                {"lot_id": lot_id},
            )
        if lot.status != "available" or lbs > _lbs(lot.remaining_lbs) + 1e-6:
            raise ApiError(
                409,
                "lot_short",
                f"Only {_lbs(lot.remaining_lbs):,.0f} lb of this lot is left, less than the "
                f"{lbs:,.0f} lb being approved. Refresh to see the latest.",
                {"lot_id": lot_id, "remaining_lbs": _lbs(lot.remaining_lbs)},
            )
    for lot_id, lbs in needed.items():
        lot = lots[lot_id]
        lot.remaining_lbs = round(_lbs(lot.remaining_lbs) - lbs, 2)
        if lot.remaining_lbs <= 0:
            lot.remaining_lbs = 0
            lot.status = "depleted"
    now = func.now()
    for a in rows:
        week = runs[a.allocation_run_id].week_start
        _log(db, a.id, user_id, "status", a.status, status)
        a.status = status
        a.final_lbs = amounts[a.id]
        a.decided_by = user_id
        a.decided_at = now
        a.delivery_date = planned_delivery(week, today)


def approve(db: Session, allocation_id: int, user_id: int, today: date) -> Allocation:
    rows, lots = _load_locked(db, [allocation_id])
    _check_undecided(rows)
    _take_stock(
        db, rows, lots, {a.id: _lbs(a.recommended_lbs) for a in rows}, user_id, today, "approved"
    )
    db.commit()
    return db.get(Allocation, allocation_id)


def bulk_approve(db: Session, ids: list[int], user_id: int, today: date) -> list[Allocation]:
    ids = sorted(set(ids))
    rows, lots = _load_locked(db, ids)
    _check_undecided(rows)
    _take_stock(
        db, rows, lots, {a.id: _lbs(a.recommended_lbs) for a in rows}, user_id, today, "approved"
    )
    db.commit()
    return rows


def edit(
    db: Session, allocation_id: int, lbs: float, note: str | None, user_id: int, today: date
) -> Allocation:
    lbs = round(lbs, 2)
    rows, lots = _load_locked(db, [allocation_id])
    _check_undecided(rows)
    row = rows[0]
    remaining = _lbs(lots[row.lot_id].remaining_lbs)
    if lbs <= 0 or lbs > remaining + 1e-6:
        raise ApiError(
            422,
            "validation_error",
            "Some fields are invalid.",
            [
                {
                    "field": "lbs",
                    "message": f"Enter more than 0 and at most {remaining:,.2f} lb, "
                    "which is what is left in this lot.",
                    "type": "value_error",
                }
            ],
        )
    old = row.recommended_lbs
    _take_stock(db, rows, lots, {row.id: lbs}, user_id, today, "edited")
    _log(db, row.id, user_id, "final_lbs", old, lbs)
    if note:
        _log(db, row.id, user_id, "note", None, note)
    db.commit()
    return db.get(Allocation, allocation_id)


def reject(db: Session, allocation_id: int, user_id: int) -> Allocation:
    row = db.scalar(select(Allocation).where(Allocation.id == allocation_id).with_for_update())
    if row is None:
        raise ApiError(404, "not_found", "Allocation not found.")
    _check_undecided([row])
    _log(db, row.id, user_id, "status", row.status, "rejected")
    row.status = "rejected"
    row.decided_by = user_id
    row.decided_at = func.now()
    db.commit()
    return db.get(Allocation, allocation_id)
