from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import SUMMARY_STATUSES
from app.models.base import Base, in_list


class MonthlySummary(Base):
    __tablename__ = "monthly_summaries"
    __table_args__ = (
        CheckConstraint(in_list("status", SUMMARY_STATUSES), name="status_valid"),
        CheckConstraint("extract(day from month) = 1", name="month_is_first_day"),
        # An admin must approve (with final text) before a summary is final.
        CheckConstraint(
            "(status = 'approved') = (approved_by IS NOT NULL AND approved_at IS NOT NULL "
            "AND final_text IS NOT NULL)",
            name="approval_complete",
        ),
        CheckConstraint(
            "status = 'approved' OR (approved_by IS NULL AND approved_at IS NULL)",
            name="draft_not_approved",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date, unique=True)
    aggregates: Mapped[dict] = mapped_column(JSONB)  # the only numbers the LLM was shown
    ai_draft: Mapped[str] = mapped_column(Text)
    final_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    model_id: Mapped[str | None] = mapped_column(String(120))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
