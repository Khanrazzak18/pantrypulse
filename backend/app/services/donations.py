"""Turning donation rows (and the model's stored output) into API responses."""

import math
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import Category, Donation, DonationItem, Donor, InventoryLot, User
from app.schemas.donations import (
    ConfirmItem,
    ConfirmRequest,
    DonationDetail,
    DonationSummary,
    ReviewItem,
)


def extracted_items(donation: Donation) -> list[dict]:
    """The model's validated items, as stored on the donation (empty if there are none)."""
    parsed = (donation.raw_llm_output or {}).get("parsed") or {}
    return parsed.get("items") or []


def _review_items_from_raw(donation: Donation) -> list[ReviewItem]:
    return [ReviewItem(**item) for item in extracted_items(donation)]


def _review_items_from_rows(db: Session, donation: Donation) -> list[ReviewItem]:
    rows = db.execute(
        select(DonationItem, Category.name)
        .join(Category, Category.id == DonationItem.category_id)
        .where(DonationItem.donation_id == donation.id)
        .order_by(DonationItem.id)
    ).all()
    return [
        ReviewItem(
            name=r.name,
            category=category,
            quantity=float(r.quantity),
            unit=r.unit,
            estimated_weight_lbs=float(r.estimated_weight_lbs),
            expiry_date=r.expiry_date,
            storage_type=r.storage_type,
            confidence=r.confidence or {},
            edited=r.edited,
        )
        for r, category in rows
    ]


def _donor_names(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return dict(db.execute(select(Donor.id, Donor.name).where(Donor.id.in_(ids))).all())


def _suggested(donation: Donation) -> str | None:
    return ((donation.raw_llm_output or {}).get("parsed") or {}).get("donor_name")


def build_summaries(db: Session, donations: list[Donation]) -> list[DonationSummary]:
    confirmed_ids = [d.id for d in donations if d.status == "confirmed"]
    totals: dict[int, tuple[int, float]] = {}
    if confirmed_ids:
        rows = db.execute(
            select(
                DonationItem.donation_id,
                func.count(),
                func.coalesce(func.sum(DonationItem.estimated_weight_lbs), 0),
            )
            .where(DonationItem.donation_id.in_(confirmed_ids))
            .group_by(DonationItem.donation_id)
        )
        totals = {donation_id: (count, float(total)) for donation_id, count, total in rows}
    donors = _donor_names(db, {d.donor_id for d in donations if d.donor_id})

    summaries = []
    for d in donations:
        if d.status == "confirmed":
            count, total = totals.get(d.id, (0, 0.0))
        else:
            items = extracted_items(d)
            count, total = len(items), sum(i["estimated_weight_lbs"] for i in items)
        summaries.append(
            DonationSummary(
                id=d.id,
                status=d.status,
                source_type=d.source_type,
                original_filename=d.original_filename,
                donor_id=d.donor_id,
                donor_name=donors.get(d.donor_id) if d.donor_id else None,
                suggested_donor_name=_suggested(d),
                item_count=count,
                total_lbs=round(total, 2),
                received_at=d.received_at,
                reviewed_at=d.reviewed_at,
            )
        )
    return summaries


def build_detail(db: Session, donation: Donation) -> DonationDetail:
    summary = build_summaries(db, [donation])[0]
    items = (
        _review_items_from_rows(db, donation)
        if donation.status == "confirmed"
        else _review_items_from_raw(donation)
    )
    raw = donation.raw_llm_output or {}
    usage = raw.get("usage") or {}
    return DonationDetail(
        **summary.model_dump(),
        items=items,
        notes=((raw.get("parsed") or {}).get("notes")),
        model_id=donation.model_id,
        latency_ms=donation.latency_ms,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
    )


# --- review decisions -------------------------------------------------------------------------


def _lock_pending(db: Session, donation_id: int) -> Donation:
    """Load a donation for update and make sure nobody has decided it yet."""
    donation = db.scalar(select(Donation).where(Donation.id == donation_id).with_for_update())
    if donation is None:
        raise ApiError(404, "not_found", "Donation not found.")
    if donation.status != "pending_review":
        raise ApiError(
            409,
            "donation_not_pending",
            f"This donation was already {donation.status.replace('_', ' ')}.",
        )
    return donation


def _problem(field: str, message: str) -> dict:
    return {"field": field, "message": message, "type": "value_error"}


def _differs(extracted: dict, item: ConfirmItem) -> bool:
    expiry = extracted.get("expiry_date")
    return (
        extracted["name"].strip() != item.name
        or extracted["category"] != item.category
        or extracted["unit"].lower() != item.unit.lower()
        or extracted["storage_type"] != item.storage_type
        or not math.isclose(extracted["quantity"], item.quantity, abs_tol=0.005)
        or not math.isclose(
            extracted["estimated_weight_lbs"], item.estimated_weight_lbs, abs_tol=0.05
        )
        or (date.fromisoformat(expiry) if expiry else None) != item.expiry_date
    )


def _resolve_donor(db: Session, payload: ConfirmRequest) -> Donor:
    if payload.donor_id is not None:
        donor = db.get(Donor, payload.donor_id)
        if donor is None:
            raise ApiError(
                422,
                "validation_error",
                "Some fields are invalid.",
                [_problem("donor_id", "That donor no longer exists. Choose another.")],
            )
        return donor
    existing = db.scalar(select(Donor).where(func.lower(Donor.name) == payload.donor_name.lower()))
    if existing:
        return existing
    donor = Donor(name=payload.donor_name, donor_type="other")
    db.add(donor)
    db.flush()
    return donor


def confirm_donation(
    db: Session, donation_id: int, user: User, payload: ConfirmRequest
) -> Donation:
    """The only place model output becomes inventory: the coordinator's edited rows, atomically."""
    donation = _lock_pending(db, donation_id)
    extracted = extracted_items(donation)
    now = datetime.now(UTC)
    today = now.date()

    problems = []
    for i, row in enumerate(payload.items):
        if row.source_index is not None and row.source_index >= len(extracted):
            problems.append(
                _problem(f"items.{i}.source_index", "This row doesn't match the upload.")
            )
        if row.expiry_date is not None and row.expiry_date < today:
            problems.append(_problem(f"items.{i}.expiry_date", "This item has already expired."))
    if problems:
        raise ApiError(422, "validation_error", "Some fields are invalid.", problems)

    donor = _resolve_donor(db, payload)
    category_ids = dict(db.execute(select(Category.name, Category.id)).all())
    for row in payload.items:
        source = extracted[row.source_index] if row.source_index is not None else None
        item = DonationItem(
            donation_id=donation.id,
            name=row.name,
            category_id=category_ids[row.category],
            quantity=row.quantity,
            unit=row.unit,
            estimated_weight_lbs=row.estimated_weight_lbs,
            expiry_date=row.expiry_date,
            storage_type=row.storage_type,
            confidence=source["confidence"] if source else {},
            edited=source is None or _differs(source, row),
        )
        db.add(item)
        db.flush()
        db.add(
            InventoryLot(
                donation_item_id=item.id,
                category_id=item.category_id,
                storage_type=row.storage_type,
                received_lbs=row.estimated_weight_lbs,
                remaining_lbs=row.estimated_weight_lbs,
                expired_lbs=0,
                received_date=donation.received_at.date(),
                expiry_date=row.expiry_date,
                status="available",
            )
        )
    donation.donor_id = donor.id
    donation.status = "confirmed"
    donation.reviewed_by = user.id
    donation.reviewed_at = now
    try:
        db.commit()
    except IntegrityError as exc:  # e.g. two requests creating the same new donor at once
        db.rollback()
        raise ApiError(
            409, "conflict", "Someone else changed this at the same time. Try again."
        ) from exc
    db.refresh(donation)
    return donation


def reject_donation(db: Session, donation_id: int, user: User) -> Donation:
    """Nothing enters inventory. The upload and the model's output are kept as an audit record."""
    donation = _lock_pending(db, donation_id)
    donation.status = "rejected"
    donation.reviewed_by = user.id
    donation.reviewed_at = datetime.now(UTC)
    db.commit()
    db.refresh(donation)
    return donation
