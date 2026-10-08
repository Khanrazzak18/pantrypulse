from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import ALLOCATION_RUN_STATUSES, ALLOCATION_STATUSES, EDIT_FIELDS, REASON_SOURCES
from app.models.base import MONDAY_CHECK, Base, in_list


class AllocationRun(Base):
    """One optimizer run for a forecast week. Re-running replaces undecided proposals."""

    __tablename__ = "allocation_runs"
    __table_args__ = (
        CheckConstraint(in_list("status", ALLOCATION_RUN_STATUSES), name="status_valid"),
        CheckConstraint(MONDAY_CHECK.format(col="week_start"), name="week_is_monday"),
        CheckConstraint(
            "delivery_date >= week_start AND delivery_date <= week_start + 6",
            name="delivery_within_week",
        ),
        CheckConstraint(
            "lots_considered >= 0 AND lots_excluded >= 0 AND reasons_ai >= 0 "
            "AND reasons_template >= 0 AND shipped_lbs >= 0",
            name="counts_nonneg",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="RESTRICT")
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20))
    week_start: Mapped[date] = mapped_column(Date)  # the forecast week being allocated
    delivery_date: Mapped[date] = mapped_column(Date)  # when approved allocations go out
    lots_considered: Mapped[int] = mapped_column(Integer, server_default="0")
    lots_excluded: Mapped[int] = mapped_column(Integer, server_default="0")  # expire first
    shipped_lbs: Mapped[float] = mapped_column(Numeric(14, 2), server_default="0")
    reasons_ai: Mapped[int] = mapped_column(Integer, server_default="0")
    reasons_template: Mapped[int] = mapped_column(Integer, server_default="0")
    reason_model_id: Mapped[str | None] = mapped_column(String(120))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Allocation(Base):
    __tablename__ = "allocations"
    __table_args__ = (
        CheckConstraint(in_list("status", ALLOCATION_STATUSES), name="status_valid"),
        CheckConstraint("recommended_lbs > 0", name="recommended_positive"),
        CheckConstraint("final_lbs IS NULL OR final_lbs >= 0", name="final_nonneg"),
        # Undecided allocations carry no decision; decided ones always say who and when.
        CheckConstraint(
            "(status = 'proposed') = (decided_by IS NULL)", name="decider_matches_status"
        ),
        CheckConstraint(
            "(status = 'proposed') = (decided_at IS NULL)", name="decided_at_matches_status"
        ),
        CheckConstraint(in_list("reason_source", REASON_SOURCES), name="reason_source_valid"),
        # What a decision must carry: an approved or edited row says how much and when; a
        # proposed or rejected one has neither.
        CheckConstraint(
            "(status = 'proposed' AND final_lbs IS NULL AND delivery_date IS NULL) "
            "OR (status IN ('approved', 'edited') AND final_lbs IS NOT NULL AND final_lbs > 0 "
            "AND delivery_date IS NOT NULL) "
            "OR (status = 'rejected' AND final_lbs IS NULL AND delivery_date IS NULL)",
            name="decision_fields",
        ),
        UniqueConstraint("allocation_run_id", "lot_id", "pantry_id"),
        Index("ix_allocations_allocation_run_id", "allocation_run_id"),
        Index("ix_allocations_pantry_id", "pantry_id"),
        Index("ix_allocations_lot_id", "lot_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    allocation_run_id: Mapped[int] = mapped_column(
        ForeignKey("allocation_runs.id", ondelete="CASCADE")
    )
    lot_id: Mapped[int] = mapped_column(ForeignKey("inventory_lots.id", ondelete="RESTRICT"))
    pantry_id: Mapped[int] = mapped_column(ForeignKey("pantries.id", ondelete="RESTRICT"))
    recommended_lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(Text)
    reason_source: Mapped[str] = mapped_column(String(10), server_default="template")
    status: Mapped[str] = mapped_column(String(20))
    final_lbs: Mapped[float | None] = mapped_column(Numeric(12, 2))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_date: Mapped[date | None] = mapped_column(Date)


class AllocationEdit(Base):
    """Audit trail: every change a coordinator makes, with old value, new value, user and time."""

    __tablename__ = "allocation_edits"
    __table_args__ = (
        CheckConstraint(in_list("field", EDIT_FIELDS), name="field_valid"),
        Index("ix_allocation_edits_allocation_id", "allocation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("allocations.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    field: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
