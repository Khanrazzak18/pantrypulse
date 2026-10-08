import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db, require_coordinator
from app.errors import ApiError
from app.models import Donation, User
from app.schemas.donations import ConfirmRequest, DonationDetail, DonationSummary
from app.services import donations as views
from app.services import intake

router = APIRouter(prefix="/api/donations", tags=["donations"])


@router.post("", status_code=201, response_model=DonationDetail)
def upload_donation(
    file: UploadFile,
    request: Request,
    user: User = Depends(require_coordinator),
    db: Session = Depends(get_db),
) -> DonationDetail:
    """Check the file, have the model read it, store it, and create a donation to review.

    Nothing is saved unless the whole thing succeeds, and no inventory is created here:
    items only become inventory when a coordinator confirms them.
    """
    data = intake.read_limited(file.file, file.size)
    prepared = intake.prepare_upload(file.filename or "", data)
    outcome = intake.extract_items(request.app.state.llm, prepared, datetime.now(UTC).date())

    storage = request.app.state.storage
    key = f"donations/{uuid.uuid4().hex}{prepared.ext}"
    storage.put(key, prepared.data, prepared.content_type)
    try:
        donation = Donation(
            donor_id=None,
            source_type=prepared.source_type,
            file_key=key,
            original_filename=prepared.filename,
            status="pending_review",
            raw_llm_output=outcome.raw,
            model_id=outcome.result.model_id,
            latency_ms=outcome.result.latency_ms,
            received_at=datetime.now(UTC),
            created_by=user.id,
        )
        db.add(donation)
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key)  # no orphaned file if the row could not be saved
        raise
    db.refresh(donation)
    return views.build_detail(db, donation)


@router.get("", response_model=list[DonationSummary], dependencies=[Depends(require_coordinator)])
def list_donations(
    status: Literal["pending_review", "confirmed", "rejected"] | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[DonationSummary]:
    query = select(Donation).order_by(Donation.created_at.desc(), Donation.id.desc()).limit(limit)
    if status:
        query = query.where(Donation.status == status)
    return views.build_summaries(db, list(db.scalars(query)))


@router.get(
    "/{donation_id}", response_model=DonationDetail, dependencies=[Depends(require_coordinator)]
)
def get_donation(donation_id: int, db: Session = Depends(get_db)) -> DonationDetail:
    donation = db.get(Donation, donation_id)
    if donation is None:
        raise ApiError(404, "not_found", "Donation not found.")
    return views.build_detail(db, donation)


@router.post("/{donation_id}/confirm", response_model=DonationDetail)
def confirm_donation(
    donation_id: int,
    body: ConfirmRequest,
    user: User = Depends(require_coordinator),
    db: Session = Depends(get_db),
) -> DonationDetail:
    """Create the donation's items and one inventory lot per item from the coordinator's rows."""
    donation = views.confirm_donation(db, donation_id, user, body)
    return views.build_detail(db, donation)


@router.post("/{donation_id}/reject", response_model=DonationDetail)
def reject_donation(
    donation_id: int,
    user: User = Depends(require_coordinator),
    db: Session = Depends(get_db),
) -> DonationDetail:
    """Add nothing to inventory. The upload stays on record as rejected."""
    donation = views.reject_donation(db, donation_id, user)
    return views.build_detail(db, donation)
