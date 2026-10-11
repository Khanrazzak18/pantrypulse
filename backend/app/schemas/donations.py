from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.intake import Category, StorageType
from app.schemas.types import LineText, SafeDate


class ReviewItem(BaseModel):
    name: str
    category: str
    quantity: float
    unit: str
    estimated_weight_lbs: float
    expiry_date: date | None
    storage_type: str
    confidence: dict[str, float]
    edited: bool = False


class DonationSummary(BaseModel):
    id: int
    status: str
    source_type: str
    original_filename: str | None
    donor_id: int | None
    donor_name: str | None
    suggested_donor_name: str | None
    item_count: int
    total_lbs: float
    received_at: datetime
    reviewed_at: datetime | None


class DonationDetail(DonationSummary):
    items: list[ReviewItem]
    notes: str | None
    model_id: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None


class DonorOut(BaseModel):
    id: int
    name: str
    donor_type: str


class ConfirmItem(BaseModel):
    name: LineText = Field(min_length=1, max_length=200)
    category: Category
    quantity: float = Field(gt=0, le=1_000_000)
    unit: LineText = Field(min_length=1, max_length=30)
    estimated_weight_lbs: float = Field(gt=0, le=100_000)
    expiry_date: SafeDate | None = None
    storage_type: StorageType
    # Which extracted row this came from (None for rows the coordinator added).
    source_index: int | None = Field(default=None, ge=0)

    @field_validator("name", "unit", mode="before")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value


class ConfirmRequest(BaseModel):
    donor_id: int | None = None
    donor_name: LineText | None = Field(default=None, max_length=120)
    items: list[ConfirmItem] = Field(min_length=1, max_length=100)

    @field_validator("donor_name", mode="before")
    @classmethod
    def _strip_donor(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @model_validator(mode="after")
    def _exactly_one_donor(self):
        if (self.donor_id is None) == (self.donor_name is None):
            raise ValueError("Choose an existing donor or enter a new donor name.")
        return self
