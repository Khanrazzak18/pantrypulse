from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

MAX_NOTE_CHARS = 500
MAX_BULK = 1000


class AllocationRunOut(BaseModel):
    id: int
    status: str  # draft | completed
    forecast_run_id: int
    week_start: date
    delivery_date: date
    created_at: datetime
    lots_considered: int
    lots_excluded: int  # expire before the delivery date, so they are not offered
    shipped_lbs: float
    rows: int
    reasons_ai: int
    reasons_template: int
    reason_model_id: str | None
    duration_ms: int | None


class LatestAllocationRun(BaseModel):
    run: AllocationRunOut | None


class PantryRef(BaseModel):
    id: int
    name: str
    county: str
    miles: float  # from the warehouse


class LotRef(BaseModel):
    id: int
    item_name: str
    category: str
    storage_type: str
    expiry_date: date | None
    remaining_lbs: float
    days_left: int | None  # until expiry, counted from the delivery date


class AllocationOut(BaseModel):
    id: int
    run_id: int
    status: str  # proposed | approved | edited | rejected
    recommended_lbs: float
    final_lbs: float | None
    delivery_date: date | None
    reason: str
    reason_source: str  # ai | template
    pantry: PantryRef
    lot: LotRef
    decided_at: datetime | None


class AllocationSummary(BaseModel):
    proposed: int
    approved: int
    edited: int
    rejected: int
    proposed_lbs: float
    approved_lbs: float  # approved plus edited, at the final amount


class AllocationList(BaseModel):
    run: AllocationRunOut | None
    week_start: date | None
    rows: list[AllocationOut]
    summary: AllocationSummary


class EditIn(BaseModel):
    lbs: float = Field(gt=0, le=1_000_000, description="New amount to send, in pounds")
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)

    @field_validator("note")
    @classmethod
    def blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class BulkApproveIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_BULK)


class BulkApproveOut(BaseModel):
    approved: int
    approved_lbs: float
