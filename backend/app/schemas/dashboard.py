from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas.types import BlockText


class Totals(BaseModel):
    lbs_distributed: float
    households_served: int
    shortage_reports: int
    pantry_weeks: int
    pantry_weeks_with_shortage: int
    stockout_pct: float | None
    received_perishable_lbs: float
    expired_perishable_lbs: float
    spoilage_pct: float | None


class WeekPoint(BaseModel):
    week_start: date
    lbs_distributed: float
    households_served: int
    shortage_reports: int
    pantry_weeks: int
    pantry_weeks_with_shortage: int
    stockout_pct: float | None
    received_perishable_lbs: float
    expired_perishable_lbs: float
    spoilage_pct: float | None


class CategoryPoint(BaseModel):
    category: str
    lbs_distributed: float
    shortage_reports: int
    spoilage_pct: float | None


class DateRange(BaseModel):
    start: date
    end: date
    data_start: date | None
    data_end: date | None


class MetricsOut(BaseModel):
    range: DateRange
    totals: Totals
    weekly: list[WeekPoint]
    by_category: list[CategoryPoint]


class SummaryOut(BaseModel):
    month: str  # YYYY-MM
    status: str  # draft | approved
    aggregates: dict[str, Any]
    ai_draft: str
    final_text: str | None
    model_id: str | None
    approved_at: datetime | None
    created_at: datetime


class SummaryResponse(BaseModel):
    summary: SummaryOut | None


class ApproveIn(BaseModel):
    text: BlockText = Field(max_length=4000)

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Write the summary text before approving.")
        return value
