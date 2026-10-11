from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.constants import CATEGORY_NAMES
from app.schemas.pantries import PantryOut
from app.schemas.types import BlockText

CategoryName = Literal[*CATEGORY_NAMES]


class ShortageReportIn(BaseModel):
    category: CategoryName
    severity: int = Field(ge=1, le=3, description="1 minor, 2 serious, 3 ran out")
    households_turned_away: int = Field(default=0, ge=0, le=100_000)
    note: BlockText | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class ShortageReportOut(BaseModel):
    id: int
    category: str
    week_start: date
    severity: int
    households_turned_away: int
    note: str | None
    updated: bool  # true when this replaced an earlier report for the same week
    updated_at: datetime


class DeliveryOut(BaseModel):
    id: int
    category: str
    item_name: str
    final_lbs: float
    delivery_date: date
    expiry_date: date | None
    edited: bool


class DeliveriesOut(BaseModel):
    pantry: PantryOut
    upcoming: list[DeliveryOut]
    recent: list[DeliveryOut]
