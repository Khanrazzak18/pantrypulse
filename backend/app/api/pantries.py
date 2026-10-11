from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import current_user, get_db, require_coordinator
from app.errors import ApiError
from app.models import Pantry, User
from app.schemas.pantries import PantryOut
from app.schemas.types import PathId

router = APIRouter(prefix="/api/pantries", tags=["pantries"])


@router.get("", response_model=list[PantryOut], dependencies=[Depends(require_coordinator)])
def list_pantries(db: Session = Depends(get_db)) -> list[Pantry]:
    return list(db.scalars(select(Pantry).order_by(Pantry.id)))


@router.get("/{pantry_id}", response_model=PantryOut)
def get_pantry(
    pantry_id: PathId, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Pantry:
    # A manager may only read their own pantry. They get 403 for every other id, existing or not,
    # so the response does not reveal which pantries exist.
    if user.role == "pantry_manager" and user.pantry_id != pantry_id:
        raise ApiError(403, "forbidden", "You do not have access to this pantry.")
    pantry = db.get(Pantry, pantry_id)
    if pantry is None:
        raise ApiError(404, "not_found", "Pantry not found.")
    return pantry
