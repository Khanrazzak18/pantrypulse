from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import (
    DONATION_SOURCES,
    DONATION_STATUSES,
    DONOR_TYPES,
    LOT_STATUSES,
    STORAGE_TYPES,
)
from app.models.base import Base, in_list


class Donor(Base):
    __tablename__ = "donors"
    __table_args__ = (CheckConstraint(in_list("donor_type", DONOR_TYPES), name="type_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    donor_type: Mapped[str] = mapped_column(String(20))


class Donation(Base):
    __tablename__ = "donations"
    __table_args__ = (
        CheckConstraint(in_list("source_type", DONATION_SOURCES), name="source_valid"),
        CheckConstraint(in_list("status", DONATION_STATUSES), name="status_valid"),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_nonneg"),
        # The donor is picked during review, so it can be empty only while a donation is pending.
        CheckConstraint(
            "status <> 'confirmed' OR donor_id IS NOT NULL", name="confirmed_has_donor"
        ),
        # Pending donations are unreviewed; rejected ones say when. Confirmed history needs neither.
        CheckConstraint(
            "(status = 'pending_review' AND reviewed_at IS NULL AND reviewed_by IS NULL) "
            "OR (status = 'rejected' AND reviewed_at IS NOT NULL) OR status = 'confirmed'",
            name="review_matches_status",
        ),
        # Raw model output is cleared only after review, and the marker is set only once it is gone.
        CheckConstraint(
            "raw_output_cleared_at IS NULL OR "
            "(raw_llm_output IS NULL AND status <> 'pending_review')",
            name="raw_cleared_after_review",
        ),
        Index("ix_donations_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    donor_id: Mapped[int | None] = mapped_column(ForeignKey("donors.id", ondelete="RESTRICT"))
    source_type: Mapped[str] = mapped_column(String(20))
    file_key: Mapped[str | None] = mapped_column(String(300))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))
    raw_llm_output: Mapped[dict | None] = mapped_column(JSONB)
    raw_output_cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_id: Mapped[str | None] = mapped_column(String(120))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DonationItem(Base):
    __tablename__ = "donation_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("estimated_weight_lbs > 0", name="weight_positive"),
        CheckConstraint(in_list("storage_type", STORAGE_TYPES), name="storage_valid"),
        Index("ix_donation_items_donation_id", "donation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    donation_id: Mapped[int] = mapped_column(ForeignKey("donations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    quantity: Mapped[float] = mapped_column(Numeric(12, 2))
    unit: Mapped[str] = mapped_column(String(30))
    estimated_weight_lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    storage_type: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    edited: Mapped[bool] = mapped_column(Boolean, server_default=false())


class InventoryLot(Base):
    __tablename__ = "inventory_lots"
    __table_args__ = (
        CheckConstraint("received_lbs > 0", name="received_positive"),
        CheckConstraint("remaining_lbs >= 0", name="remaining_nonneg"),
        CheckConstraint("expired_lbs >= 0", name="expired_nonneg"),
        CheckConstraint("remaining_lbs + expired_lbs <= received_lbs", name="lbs_add_up"),
        CheckConstraint(in_list("storage_type", STORAGE_TYPES), name="storage_valid"),
        CheckConstraint(in_list("status", LOT_STATUSES), name="status_valid"),
        Index("ix_inventory_lots_expiry_date", "expiry_date"),
        Index("ix_inventory_lots_received_date", "received_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    donation_item_id: Mapped[int] = mapped_column(
        ForeignKey("donation_items.id", ondelete="RESTRICT")
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    storage_type: Mapped[str] = mapped_column(String(20))
    received_lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    remaining_lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    expired_lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    received_date: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
