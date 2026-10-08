from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_db, require_coordinator
from app.models import Donor
from app.schemas.donations import DonorOut

router = APIRouter(
    prefix="/api/donors", tags=["donors"], dependencies=[Depends(require_coordinator)]
)


@router.get("", response_model=list[DonorOut])
def list_donors(db: Session = Depends(get_db)) -> list[Donor]:
    return list(db.scalars(select(Donor).order_by(func.lower(Donor.name))))
