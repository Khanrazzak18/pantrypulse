"""The AI monthly summary: aggregates in, a checked draft out, an admin approves the final text."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_provider import LLMError, LLMProvider
from app.ai.prompts import load_prompt
from app.errors import ApiError
from app.models import MonthlySummary
from app.schemas.intake import inline_refs
from app.schemas.types import strip_controls
from app.services import dashboard
from app.services.number_check import unsupported_numbers

logger = logging.getLogger("pantrypulse.summary")
TOOL_NAME = "record_summary"
TIMEOUT_SECONDS = 15.0


class SummaryOutput(BaseModel):
    summary: str = Field(min_length=20, max_length=2000)


def parse_month(month: str) -> date:
    return date(int(month[:4]), int(month[5:7]), 1)


def _next_month(first: date) -> date:
    return (first + timedelta(days=32)).replace(day=1)


def _mondays(first: date) -> tuple[date, date]:
    """The first and last Monday that fall inside the month."""
    start = first + timedelta(days=(7 - first.weekday()) % 7)
    end = dashboard.monday_of(_next_month(first) - timedelta(days=1))
    return start, end


def _totals(db: Session, first: date) -> dict:
    start, end = _mondays(first)
    m = dashboard.metrics(db, start, end)
    t = m["totals"]
    return {
        "month_label": f"{first:%B %Y}",
        "weeks_with_data": sum(1 for w in m["weekly"] if w["pantry_weeks"] > 0),
        "pounds_distributed": round(t["lbs_distributed"]),
        "households_served": t["households_served"],
        "shortage_reports": t["shortage_reports"],
        "pantry_weeks_with_shortage_pct": t["stockout_pct"],
        "received_perishable_lbs": round(t["received_perishable_lbs"]),
        "expired_perishable_lbs": round(t["expired_perishable_lbs"]),
        "spoilage_pct": t["spoilage_pct"],
        "by_category": [
            {
                "category": c["category"],
                "pounds_distributed": round(c["lbs_distributed"]),
                "shortage_reports": c["shortage_reports"],
                "spoilage_pct": c["spoilage_pct"],
            }
            for c in m["by_category"]
            if c["lbs_distributed"] or c["shortage_reports"]
        ],
    }


def _has_data(totals: dict) -> bool:
    return bool(
        totals["weeks_with_data"] or totals["shortage_reports"] or totals["received_perishable_lbs"]
    )


def monthly_aggregates(db: Session, month: str) -> dict:
    """The only numbers the model is ever shown: totals for the month and the month before."""
    first = parse_month(month)
    current = _totals(db, first)
    previous = _totals(db, (first - timedelta(days=1)).replace(day=1))
    previous.pop("by_category")
    current["previous_month"] = previous if _has_data(previous) else None
    return current


def _flatten(value, out: set[float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        out.update({float(value), float(round(value)), round(float(value), 1)})
    elif isinstance(value, dict):
        for v in value.values():
            _flatten(v, out)
    elif isinstance(value, list):
        for v in value:
            _flatten(v, out)


def allowed_numbers(aggregates: dict, first: date) -> set[float]:
    allowed: set[float] = set()
    _flatten(aggregates, allowed)
    allowed.update({float(first.year), float(first.month)})
    prev = (first - timedelta(days=1)).replace(day=1)
    allowed.update({float(prev.year), float(prev.month)})
    return allowed


def get(db: Session, month: str) -> MonthlySummary | None:
    return db.scalar(select(MonthlySummary).where(MonthlySummary.month == parse_month(month)))


def _approved_conflict() -> ApiError:
    return ApiError(
        409, "summary_approved", "This month's summary is already approved and can't be changed."
    )


def draft(db: Session, llm: LLMProvider, month: str) -> MonthlySummary:
    existing = get(db, month)
    if existing is not None and existing.status == "approved":
        raise _approved_conflict()
    first = parse_month(month)
    aggregates = monthly_aggregates(db, month)
    if not _has_data(aggregates):
        raise ApiError(422, "no_data", f"There is no data for {first:%B %Y} to summarise yet.")
    try:
        result = llm.converse_tool(
            system=load_prompt("monthly_summary"),
            content=[{"text": json.dumps(aggregates)}, {"text": "Write the summary."}],
            tool_name=TOOL_NAME,
            tool_description="Record the monthly summary text",
            input_schema=inline_refs(SummaryOutput.model_json_schema()),
            max_tokens=800,
            timeout_seconds=TIMEOUT_SECONDS,
        )
    except LLMError as exc:
        logger.warning("summary_failed", extra={"error": type(exc).__name__})
        raise _failed(
            "The AI service did not answer in time. Try again, or write it yourself."
        ) from exc
    logger.info(
        "summary_call",
        extra={"model": result.model_id, "input_tokens": result.input_tokens,
               "output_tokens": result.output_tokens, "latency_ms": result.latency_ms},
    )  # fmt: skip
    try:
        if result.tool_input is None:
            raise ValueError("no tool call")
        text = strip_controls(
            SummaryOutput.model_validate(result.tool_input).summary, keep_newlines=True
        ).strip()
    except (ValidationError, ValueError) as exc:
        raise _failed(
            "The AI returned an unusable draft. Try again, or write it yourself."
        ) from exc
    bad = unsupported_numbers(text, allowed_numbers(aggregates, first))
    if bad:
        shown = ", ".join(f"{n:g}" for n in bad)
        raise ApiError(
            502,
            "summary_numbers_mismatch",
            f"The draft contained numbers that are not in the data ({shown}), so it was not "
            "saved. Try again, or write it yourself.",
            {"numbers": bad},
        )
    if existing is None:
        existing = MonthlySummary(month=first, status="draft")
        db.add(existing)
    existing.aggregates = aggregates
    existing.ai_draft = text
    existing.model_id = result.model_id
    db.commit()
    db.refresh(existing)
    return existing


def _failed(message: str) -> ApiError:
    return ApiError(502, "summary_failed", message)


def approve(db: Session, month: str, text: str, user_id: int) -> MonthlySummary:
    row = get(db, month)
    if row is not None and row.status == "approved":
        raise _approved_conflict()
    if row is None:
        row = MonthlySummary(
            month=parse_month(month), aggregates=monthly_aggregates(db, month), ai_draft=""
        )
        db.add(row)
    row.final_text = text
    row.status = "approved"
    row.approved_by = user_id
    row.approved_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row
