"""Retention of raw model output.

The raw tool input the model returned is kept on the donation as audit evidence: it is how a
reviewer, an auditor or a grant funder can see what the model said versus what a coordinator
confirmed. It is not needed afterwards, and it can quote donor text, so it is cleared a fixed time
after the donation was reviewed. The model id, latency, token counts, the confirmed items and the
edit flags stay. Donations still waiting for review are never touched.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import null, update
from sqlalchemy.orm import Session

from app.models import Donation

RETENTION_DAYS = 90
logger = logging.getLogger("pantrypulse.retention")


def clear_old_raw_output(db: Session, today: date, days: int = RETENTION_DAYS) -> int:
    """Clear raw output reviewed more than `days` days before `today`. Returns how many rows."""
    cutoff = datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(days=days)
    result = db.execute(
        update(Donation)
        .where(
            Donation.status.in_(("confirmed", "rejected")),
            Donation.reviewed_at.is_not(None),
            Donation.reviewed_at < cutoff,
            Donation.raw_llm_output.is_not(None),
        )
        .values(
            raw_llm_output=null(),  # SQL NULL, not the JSON value null
            raw_output_cleared_at=datetime.now(UTC),
        )
    )
    cleared = result.rowcount or 0
    logger.info("raw_output_cleared", extra={"count": cleared, "retention_days": days})
    return cleared
