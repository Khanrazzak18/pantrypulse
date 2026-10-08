from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import ALLOCATION_RUN_STATUSES, ALLOCATION_STATUSES
from app.models.base import Base, in_list


class AllocationRun(Base):
    __tablename__ = "allocation_runs"
    __table_args__ = (
        CheckConstraint(in_list("status", ALLOCATION_RUN_STATUSES), name="status_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="RESTRICT")
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20))
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
        Index("ix_allocations_allocation_run_id", "allocation_run_id"),
        Index("ix_allocations_pantry_id", "pantry_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    allocation_run_id: Mapped[int] = mapped_column(
        ForeignKey("allocation_runs.id", ondelete="CASCADE")
    )
    lot_id: Mapped[int] = mapped_column(ForeignKey("inventory_lots.id", ondelete="RESTRICT"))
    pantry_id: Mapped[int] = mapped_column(ForeignKey("pantries.id", ondelete="RESTRICT"))
    recommended_lbs: Mapped[float] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    final_lbs: Mapped[float | None] = mapped_column(Numeric(12, 2))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_date: Mapped[date | None] = mapped_column(Date)


class AllocationEdit(Base):
    """Audit trail: every change a coordinator makes, with old value, new value, user and time."""

    __tablename__ = "allocation_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("allocations.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    field: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
